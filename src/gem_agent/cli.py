from __future__ import annotations

import json
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from .approval import ApprovalGate
from .db import Database
from .pipeline import TenderPipeline
from .scout.cppp import manual_tender

app = typer.Typer(add_completion=False, no_args_is_help=True, help="GeM / gov tender operator agent")
console = Console()


@app.command("scout")
def scout_cmd(
    pages: int = typer.Option(1, help="GeM pages per keyword query"),
    no_cppp: bool = typer.Option(False, help="Skip CPPP best-effort scout"),
) -> None:
    """Discover and score matching GeM (and optional CPPP) tenders."""
    pipe = TenderPipeline()
    scored = pipe.scout(pages_per_query=pages, include_cppp=not no_cppp)
    console.print(f"[green]Matched {len(scored)} tenders[/green]")
    pipe.print_table()


@app.command("list")
def list_cmd(min_score: float = 0.35, limit: int = 40) -> None:
    """List scored tenders from the local database."""
    pipe = TenderPipeline()
    rows = pipe.db.list_tenders(min_score=min_score, limit=limit)
    pipe.print_table(rows)


@app.command("analyze")
def analyze_cmd(bid_number: str) -> None:
    """Analyse a tender (LLM if OPENAI_API_KEY set, else heuristics)."""
    pipe = TenderPipeline()
    bid_number = _resolve_bid(pipe.db, bid_number)
    result = pipe.analyze(bid_number)
    console.print(
        Panel.fit(
            json.dumps(result.model_dump(), indent=2),
            title=f"Analysis {bid_number}",
        )
    )


def _resolve_bid(db: Database, bid_number: str) -> str:
    row = db.get_by_bid_number(bid_number)
    if row:
        return bid_number
    # Allow prefix match when the table truncates long bid numbers.
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT bid_number FROM tenders WHERE bid_number LIKE ? ORDER BY fit_score DESC LIMIT 5",
            (f"{bid_number}%",),
        ).fetchall()
    if len(rows) == 1:
        return rows[0]["bid_number"]
    if not rows:
        raise typer.BadParameter(f"Unknown bid {bid_number}")
    options = ", ".join(r["bid_number"] for r in rows)
    raise typer.BadParameter(f"Ambiguous bid prefix {bid_number}. Candidates: {options}")


@app.command("draft")
def draft_cmd(bid_number: str) -> None:
    """Generate a technical bid draft markdown and mark approval pending."""
    pipe = TenderPipeline()
    bid_number = _resolve_bid(pipe.db, bid_number)
    path = pipe.draft(bid_number)
    console.print(f"[green]Draft written:[/green] {path}")
    console.print(f"Review the draft, then: [bold]gem-agent approve '{bid_number}'[/bold]")


@app.command("approve")
def approve_cmd(bid_number: str, note: str = "") -> None:
    gate = ApprovalGate()
    bid_number = _resolve_bid(gate.db, bid_number)
    result = gate.approve(bid_number, note)
    console.print(result.message)


@app.command("reject")
def reject_cmd(bid_number: str, note: str = "") -> None:
    gate = ApprovalGate()
    bid_number = _resolve_bid(gate.db, bid_number)
    result = gate.reject(bid_number, note)
    console.print(result.message)


@app.command("assist-submit")
def assist_submit_cmd(
    bid_number: str,
    confirm: bool = typer.Option(False, "--confirm", help="Generate assisted checklist (no live bid)"),
) -> None:
    """Human-approved assisted submit checklist. Does not place a live GeM bid in v1."""
    gate = ApprovalGate()
    bid_number = _resolve_bid(gate.db, bid_number)
    result = gate.assist_submit(bid_number, confirm=confirm)
    console.print(result.message)


@app.command("contractor-fit")
def contractor_fit_cmd(
    pages: int = typer.Option(2, help="GeM pages per query"),
    max_docs: int = typer.Option(55, help="Max bid PDFs to enrich"),
) -> None:
    """AI-training contractor scan: no EMD, ≤2y exp, ≤40L turnover, ≥7d deadline, Pathankot rank."""
    from .scout.contractor_fit import print_table, run_contractor_fit_scout, save_report

    payload = run_contractor_fit_scout(pages=pages, max_docs=max_docs)
    print_table(payload.get("matches") or [])
    path = save_report(payload)
    console.print(
        f"[bold]{len(payload.get('matches') or [])}[/bold] eligible matches. "
        f"Watchlist={len(payload.get('watchlist_leads') or [])} "
        f"CPPP={len(payload.get('cppp_leads') or [])}. Report: {path}"
    )


@app.command("daily")
def daily_cmd(top: int = 10, analyze: bool = True) -> None:
    """Run scout + optional top-N analyse + notify digest."""
    pipe = TenderPipeline()
    result = pipe.run_daily(top_n=top, auto_analyze=analyze)
    console.print(f"Matched={result['matched']} analyzed={result['analyzed']}")
    pipe.print_table()


@app.command("add-manual")
def add_manual_cmd(
    bid_number: str,
    title: str,
    url: Optional[str] = None,
    ministry: Optional[str] = None,
    score: float = 0.7,
) -> None:
    """Manually add a tender (useful when you paste a GeM link)."""
    pipe = TenderPipeline()
    tender = manual_tender(bid_number=bid_number, title=title, url=url, ministry=ministry)
    pipe.db.upsert_tender(tender, fit_score=score, matched_keywords=["manual"], reasons=["Manual entry"])
    console.print(f"Added {bid_number}")


@app.command("started-from")
def started_from_cmd(
    pages: int = typer.Option(3, help="GeM pages per keyword query"),
    since: Optional[str] = typer.Option(
        None,
        help="ISO date YYYY-MM-DD for start_at lower bound (default: today)",
    ),
) -> None:
    """List keyword-matched GeM bids with start_at >= today (or --since). No end-date cutoff."""
    from datetime import datetime, timezone

    from .scout.started_from import run_started_from_scout, save_started_from_report

    floor = None
    if since:
        floor = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    payload = run_started_from_scout(start_on_or_after=floor, pages=pages)
    path = save_started_from_report(payload)
    console.print(
        f"[bold]{payload.get('count', 0)}[/bold] tenders with start ≥ "
        f"{payload.get('start_on_or_after')} (no end filter). Report: {path}"
    )


@app.command("show")
def show_cmd(bid_number: str) -> None:
    db = Database()
    row = db.get_by_bid_number(bid_number)
    if not row:
        raise typer.Exit(code=1)
    console.print_json(data={k: row[k] for k in row.keys()})


@app.command("hub-scrape")
def hub_scrape_cmd(
    portals: Optional[str] = typer.Option(
        None,
        help="Comma-separated: tendersplus,gem,cppp,punjab,bank_auction,gov_auction,vehicles,olx",
    ),
) -> None:
    """Scrape all Pathankot Pulse portals into sectioned leads (default region 145023)."""
    from .hub import run_hub_scrape

    selected = [p.strip() for p in portals.split(",")] if portals else None
    result = run_hub_scrape(portals=selected)
    console.print(Panel.fit(json.dumps(result, indent=2), title="Pathankot Pulse scrape"))


@app.command("tendersplus")
def tendersplus_cmd(
    keyword: str = typer.Option("Steel Bars", help="Keyword to scrape (all pages)"),
    max_pages: Optional[int] = typer.Option(
        None,
        help="Cap pages (default: all pages for this keyword; site = 10 rows/page)",
    ),
    year: int = typer.Option(2026, help="Listing year"),
) -> None:
    """Deep-scrape TendersPlus active tenders for one keyword across all pages."""
    from .hub.store import Lead, load_hub_config, load_leads, save_leads
    from .hub.tendersplus import scrape_tendersplus_all_for_keyword

    def _persist(leads: list, meta: dict) -> None:
        existing = load_leads().get("by_portal") or {}
        by_portal: dict = {}
        for portal, rows in existing.items():
            if portal == "tendersplus":
                continue
            by_portal[portal] = [
                Lead(**{k: v for k, v in row.items() if k in Lead.__dataclass_fields__})
                if isinstance(row, dict)
                else row
                for row in rows
            ]
        prev = existing.get("tendersplus") or []
        all_leads: list = []
        seen: set[str] = set()
        for item in list(leads) + [
            Lead(**{k: v for k, v in row.items() if k in Lead.__dataclass_fields__})
            if isinstance(row, dict)
            else row
            for row in prev
        ]:
            uid = (item.meta or {}).get("uuid") if isinstance(item, Lead) else ""
            key = uid or (item.url if isinstance(item, Lead) else "")
            if not key or key in seen:
                continue
            seen.add(key)
            all_leads.append(item)
        # Prefer keeping non-steel keyword leads + new keyword leads
        by_portal["tendersplus"] = all_leads
        path = save_leads(by_portal, region=(load_hub_config().get("region")))
        console.print(
            f"  checkpoint page={meta.get('pages_fetched')}/{meta.get('total_pages')} "
            f"keyword_leads={meta.get('stored')} store={len(all_leads)} → {path}"
        )

    leads, meta = scrape_tendersplus_all_for_keyword(
        keyword,
        max_pages=max_pages,
        year=year,
        checkpoint_every=25,
        on_checkpoint=_persist,
    )
    _persist(leads, meta)
    console.print(
        f"[green]TendersPlus DONE[/green] keyword={keyword!r} pages={meta.get('pages_fetched')}/"
        f"{meta.get('total_pages')} total_reported={meta.get('total')} keyword_leads={len(leads)}"
    )


@app.command("serve")
def serve_cmd(
    host: str = "0.0.0.0",
    port: int = 8787,
) -> None:
    """Start Pathankot Pulse UI + API (default binds for LAN/public deploy)."""
    import uvicorn

    uvicorn.run("gem_agent.api:app", host=host, port=port, reload=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
