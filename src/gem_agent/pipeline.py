from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from .analyst import analyze_tender
from .approval import ApprovalGate
from .config import get_settings, load_keywords, load_profile
from .db import Database
from .matcher import rank_tenders
from .models import AnalysisResult, ScoredTender, Tender
from .notify import notify
from .proposal import draft_proposal
from .scout.cppp import CpppScout
from .scout.gem import GemScout

console = Console()


class TenderPipeline:
    def __init__(self, db: Database | None = None) -> None:
        self.settings = get_settings()
        self.db = db or Database()
        self.profile = load_profile(self.settings)
        self.keywords = load_keywords(self.settings)
        self.gate = ApprovalGate(self.db)

    def scout(self, *, pages_per_query: int = 1, include_cppp: bool = True) -> list[ScoredTender]:
        gem_queries = list(self.keywords.get("gem_queries") or [])
        cppp_queries = list(self.keywords.get("cppp_queries") or [])

        tenders: list[Tender] = []
        with GemScout() as gem:
            tenders.extend(gem.search_many(gem_queries, pages_per_query=pages_per_query))

        if include_cppp:
            with CpppScout() as cppp:
                try:
                    tenders.extend(cppp.search_many(cppp_queries))
                except Exception as exc:  # noqa: BLE001
                    console.print(f"[yellow]CPPP scout skipped: {exc}[/yellow]")

        scored = rank_tenders(tenders, keywords=self.keywords, profile=self.profile)
        for item in scored:
            self.db.upsert_tender(
                item.tender,
                fit_score=item.fit_score,
                matched_keywords=item.matched_keywords,
                reasons=item.reasons,
            )
        self.db.log_action("scout", details=f"fetched={len(tenders)} matched={len(scored)}")
        return scored

    def analyze(self, bid_number: str) -> AnalysisResult:
        row = self.db.get_by_bid_number(bid_number)
        if not row:
            raise ValueError(f"Unknown bid {bid_number}. Run scout first or add-manual.")
        tender = self.db.tender_from_row(row)
        analysis = analyze_tender(tender, self.profile)
        self.db.save_analysis(bid_number, decision=analysis.decision, analysis=analysis.model_dump())
        self.db.log_action("analyze", bid_number, analysis.decision.value)
        return analysis

    def draft(self, bid_number: str) -> str:
        row = self.db.get_by_bid_number(bid_number)
        if not row:
            raise ValueError(f"Unknown bid {bid_number}")
        tender = self.db.tender_from_row(row)
        if row.get("analysis_json"):
            import json

            from .models import Decision

            raw = json.loads(row["analysis_json"])
            analysis = AnalysisResult(
                decision=Decision(raw.get("decision", "maybe")),
                summary=raw.get("summary", ""),
                eligibility_notes=raw.get("eligibility_notes") or [],
                risks=raw.get("risks") or [],
                required_docs=raw.get("required_docs") or [],
                suggested_approach=raw.get("suggested_approach") or "",
                confidence=float(raw.get("confidence") or 0.5),
                used_llm=bool(raw.get("used_llm")),
            )
        else:
            analysis = self.analyze(bid_number)
        proposal = draft_proposal(tender, analysis, profile=self.profile)
        assert proposal.path
        self.db.set_proposal_path(bid_number, proposal.path)
        self.gate.request_approval(bid_number, "Draft ready — review before any portal action")
        self.db.log_action("draft", bid_number, proposal.path)
        return proposal.path

    def run_daily(self, *, top_n: int = 10, auto_analyze: bool = True) -> dict[str, Any]:
        scored = self.scout(pages_per_query=1, include_cppp=True)
        top = scored[:top_n]
        analyzed = 0
        if auto_analyze:
            for item in top:
                self.analyze(item.tender.bid_number)
                analyzed += 1

        lines = [f"GeM Tender Agent daily digest — {len(scored)} matches (showing top {len(top)})"]
        for item in top:
            lines.append(
                f"• [{item.fit_score:.2f}] {item.tender.bid_number} — {item.tender.title[:90]}"
            )
        digest = "\n".join(lines)
        notify(digest)
        self.db.log_action("daily", details=digest)
        return {"matched": len(scored), "analyzed": analyzed, "top": [s.model_dump(mode="json") for s in top]}

    def print_table(self, rows: list[dict[str, Any]] | None = None, min_score: float = 0.35) -> None:
        rows = rows if rows is not None else self.db.list_tenders(min_score=min_score, limit=40)
        table = Table(title="Matched tenders")
        table.add_column("Score", justify="right")
        table.add_column("Bid")
        table.add_column("Title")
        table.add_column("Decision")
        table.add_column("End")
        table.add_column("Approval")
        for row in rows:
            table.add_row(
                f"{float(row.get('fit_score') or 0):.2f}",
                row.get("bid_number") or "",
                (row.get("title") or "")[:70],
                row.get("decision") or "-",
                (row.get("end_at") or "")[:10],
                row.get("approval_status") or "-",
            )
        console.print(table)
