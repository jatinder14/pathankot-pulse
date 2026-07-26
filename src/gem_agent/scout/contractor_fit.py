"""Fit filter for new AI-training contractor near Pathankot.

Rules (company profile):
- No EMD / EMD EXEMPT / EMD Nil / 0
- Deadline at least min_days_to_deadline (default 7) away
- Required experience years <= max (default 2)
- Required turnover <= last year turnover (default 40 lakh)
- Rank by proximity to Pathankot, Punjab
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from rich.console import Console
from rich.table import Table

from ..config import OUTPUT_DIR, get_settings, load_keywords, load_profile
from ..matcher import rank_tenders
from .gem import BASE, GemScout
from .cppp import CpppScout

console = Console()

PATHANKOT_NEAR = {
    "Pathankot": 100,
    "Gurdaspur": 85,
    "Kangra": 75,
    "Nurpur": 70,
    "Mukerian": 65,
    "Hoshiarpur": 60,
    "Amritsar": 55,
    "Jammu": 50,
    "Dasuya": 48,
    "Jalandhar": 40,
    "Ludhiana": 25,
    "Mohali": 20,
    "Chandigarh": 18,
    "Patiala": 15,
    "Bathinda": 10,
}

NEAR_STATES = {
    "Punjab": 35,
    "Himachal Pradesh": 22,
    "Jammu And Kashmir": 20,
    "Jammu and Kashmir": 20,
    "Chandigarh": 15,
    "Haryana": 12,
    "Uttarakhand": 5,
    "Delhi": 3,
}


def _pdf_text(content: bytes, max_pages: int = 12) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])


def parse_emd(text: str) -> tuple[float | None, bool, str]:
    text_n = re.sub(r"\s+", " ", text or "")

    # GeM bilingual PDF table: "/EMD Detail ... /Required No" (or Yes)
    gem_req = re.search(
        r"/?\s*EMD\s*Detail.{0,120}?/?\s*Required\s*(Yes|No)\b",
        text_n,
        re.I,
    )
    if gem_req:
        if gem_req.group(1).lower() == "no":
            return 0.0, True, gem_req.group(0)[:160]
        # Required Yes — try to capture amount nearby; treat as not free if unknown
        amt_near = re.search(
            r"/?\s*EMD\s*Detail.{0,200}?(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
            text_n,
            re.I,
        )
        if amt_near:
            try:
                amount = float(amt_near.group(1).replace(",", ""))
                if amount == 0:
                    return 0.0, True, amt_near.group(0)[:160]
                return amount, False, amt_near.group(0)[:160]
            except ValueError:
                pass
        return None, False, gem_req.group(0)[:160]

    explicit = re.search(
        r"(?:EMD|Earnest Money(?: Deposit)?|Bid Security|ePBG)\s*"
        r"(?:Amount|Detail|Required)?\s*[:\-/]?\s*"
        r"(Nil|NIL|N\.?A\.?|Not Applicable|Not required|Not Required|Exempt(?:ed)?|Zero|No|0(?:\.0+)?)",
        text_n,
        re.I,
    )
    if explicit:
        return 0.0, True, explicit.group(0)[:140]

    amount = None
    evidence = ""
    for pat in [
        r"(?:EMD|Earnest Money(?: Deposit)?|Bid Security)\s*(?:Amount)?\s*[:\-]?\s*(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]:
        m = re.search(pat, text_n, re.I)
        if m and m.group(1).strip():
            try:
                amount = float(m.group(1).replace(",", ""))
                evidence = m.group(0)[:140]
                break
            except ValueError:
                continue
    if amount is None:
        return None, False, "EMD not found"
    if amount == 0:
        return 0.0, True, evidence
    return amount, False, evidence


def parse_experience_years(text: str) -> tuple[float | None, str]:
    text_n = re.sub(r"\s+", " ", text or "")
    patterns = [
        r"(?:minimum|min\.?|at least)?\s*(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*years?\s+(?:of\s+)?(?:relevant\s+)?(?:work\s+)?experience",
        r"experience\s+(?:of\s+)?(?:minimum|min\.?|at least)?\s*(\d+(?:\.\d+)?)\s*years?",
        r"(\d+(?:\.\d+)?)\s*years?\s+(?:in\s+)?(?:similar|relevant|past)\s+(?:work|experience|projects?)",
        r"past experience[^\d]{0,40}(\d+(?:\.\d+)?)\s*years?",
        r"Past Experience Required[^\d]{0,60}(\d+(?:\.\d+)?)\s*Years?",
    ]
    for pat in patterns:
        m = re.search(pat, text_n, re.I)
        if m:
            try:
                return float(m.group(1)), m.group(0)[:140]
            except ValueError:
                continue
    if re.search(r"experience\s*(:|-)?\s*(not required|nil|na|n/?a)", text_n, re.I):
        return 0.0, "experience not required"
    return None, "experience not found"


def _to_inr(amount: float, unit_hint: str) -> float:
    u = unit_hint.lower()
    if "crore" in u or "cr" in u:
        return amount * 10_000_000
    if "lakh" in u or "lac" in u:
        return amount * 100_000
    return amount


def parse_turnover(text: str) -> tuple[float | None, str]:
    text_n = re.sub(r"\s+", " ", text or "")
    patterns = [
        r"(?:average|avg\.?|minimum|min\.?|annual)?\s*(?:turnover|revenue)\s*"
        r"(?:of\s+)?(?:at least\s+|minimum\s+|not less than\s+)?"
        r"(?:Rs\.?|INR|₹)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh|lac|lakhs|lacs)?",
        r"turnover[^\d]{0,30}([0-9][0-9,]*(?:\.[0-9]+)?)\s*(crore|cr|lakh|lac|lakhs|lacs)",
    ]
    for pat in patterns:
        m = re.search(pat, text_n, re.I)
        if m:
            try:
                raw = float(m.group(1).replace(",", ""))
                unit = m.group(2) or ""
                return _to_inr(raw, unit), m.group(0)[:160]
            except ValueError:
                continue
    if re.search(r"turnover\s*(:|-)?\s*(not required|nil|na|n/?a|exempt)", text_n, re.I):
        return 0.0, "turnover not required"
    return None, "turnover not found"


def parse_locations(text: str) -> tuple[list[str], list[str]]:
    text_n = re.sub(r"\s+", " ", text or "")
    states = re.findall(
        r"\b(Punjab|Haryana|Himachal Pradesh|Jammu and Kashmir|Delhi|Chandigarh|"
        r"Rajasthan|Uttar Pradesh|Maharashtra|Karnataka|Tamil Nadu|Gujarat|"
        r"West Bengal|Bihar|Madhya Pradesh|Odisha|Assam|Telangana|Andhra Pradesh|"
        r"Kerala|Uttarakhand)\b",
        text_n,
        re.I,
    )
    cities = re.findall(r"\b(" + "|".join(PATHANKOT_NEAR.keys()) + r")\b", text_n, re.I)
    return sorted({s.title() for s in states}), sorted({c.title() for c in cities})


def proximity_score(states: list[str], cities: list[str]) -> int:
    score = 0
    for c in cities:
        score = max(score, PATHANKOT_NEAR.get(c, 0))
    for s in states:
        score += NEAR_STATES.get(s, 0)
    return score


def enrich(gem: GemScout, tender: Any) -> dict[str, Any]:
    eid = tender.external_id
    text = ""
    try:
        r = gem._client.get(f"{BASE}/showbidDocument/{eid}", timeout=60.0)
        if r.status_code == 200 and r.content.startswith(b"%PDF"):
            text = _pdf_text(r.content)
        else:
            h = gem._client.get(f"{BASE}/bidding/bid/getBidResultView/{eid}", timeout=60.0)
            text = h.text
    except Exception as exc:  # noqa: BLE001
        return {
            "bid_number": tender.bid_number,
            "title": tender.title,
            "error": str(exc),
            "eligible": False,
            "reasons": [f"fetch failed: {exc}"],
            "proximity": 0,
        }

    emd, no_emd, emd_ev = parse_emd(text)
    exp, exp_ev = parse_experience_years(text)
    turnover, turn_ev = parse_turnover(text)
    states, cities = parse_locations(text)
    prox = proximity_score(states, cities)

    return {
        "bid_number": tender.bid_number,
        "external_id": eid,
        "title": tender.title,
        "ministry": tender.ministry,
        "department": tender.department,
        "end_at": tender.end_at.isoformat() if tender.end_at else None,
        "end_dt": tender.end_at,
        "url": tender.url,
        "emd_amount": emd,
        "no_emd": no_emd,
        "emd_evidence": emd_ev,
        "experience_years_required": exp,
        "experience_evidence": exp_ev,
        "turnover_required_inr": turnover,
        "turnover_evidence": turn_ev,
        "states": states,
        "cities": cities,
        "proximity": prox,
        "doc_excerpt": re.sub(r"\s+", " ", text)[:400],
    }


def apply_company_filters(
    rows: list[dict[str, Any]],
    *,
    max_exp: float,
    max_turnover: float,
    min_days: int,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    min_end = now + timedelta(days=min_days)
    out: list[dict[str, Any]] = []
    for r in rows:
        reasons: list[str] = []
        ok = True

        if not r.get("no_emd"):
            ok = False
            reasons.append(f"EMD not free ({r.get('emd_amount')}: {r.get('emd_evidence')})")

        end_dt = r.get("end_dt")
        if end_dt is None:
            ok = False
            reasons.append("deadline missing")
        else:
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if end_dt < min_end:
                ok = False
                reasons.append(f"deadline too soon ({end_dt.date()} < {min_end.date()})")

        exp = r.get("experience_years_required")
        if exp is not None and exp > max_exp:
            ok = False
            reasons.append(f"experience required {exp}y > company max {max_exp}y")

        turnover = r.get("turnover_required_inr")
        if turnover is not None and turnover > max_turnover:
            ok = False
            reasons.append(
                f"turnover required ₹{turnover:,.0f} > company ₹{max_turnover:,.0f}"
            )

        # If experience/turnover unknown, keep but flag (new company — still worth review)
        notes: list[str] = []
        if exp is None:
            notes.append("experience clause not found — verify PDF")
        if turnover is None:
            notes.append("turnover clause not found — verify PDF")

        r["eligible"] = ok
        r["reasons"] = reasons
        r["notes"] = notes
        if ok:
            out.append(r)
    out.sort(key=lambda x: (-int(x.get("proximity") or 0), x.get("end_at") or "9999"))
    return out


def probe_watchlist(portals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort public page probe — returns soft leads (manual follow-up)."""
    import httpx

    leads: list[dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GodHandTrainBot/0.1)"}
    with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
        for p in portals:
            url = p.get("url") or ""
            name = p.get("name") or url
            try:
                resp = client.get(url)
                text = resp.text.lower()
                hits = [
                    k
                    for k in (
                        "ai",
                        "artificial intelligence",
                        "capacity building",
                        "training",
                        "digital literacy",
                        "rfe",
                        "empanelment",
                        "tender",
                    )
                    if k in text
                ]
                leads.append(
                    {
                        "source": "watchlist",
                        "name": name,
                        "url": url,
                        "notes": p.get("notes"),
                        "status_code": resp.status_code,
                        "keyword_hits": hits[:8],
                        "manual_check": True,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                leads.append(
                    {
                        "source": "watchlist",
                        "name": name,
                        "url": url,
                        "error": str(exc),
                        "manual_check": True,
                    }
                )
    return leads


def run_contractor_fit_scout(
    *,
    pages: int = 2,
    max_docs: int = 55,
) -> dict[str, Any]:
    settings = get_settings()
    profile = load_profile(settings)
    keywords = load_keywords(settings)
    policy = profile.get("bid_policy") or {}
    elig = profile.get("eligibility_defaults") or {}

    max_exp = float(policy.get("max_experience_years_required") or elig.get("years_experience") or 2)
    max_turnover = float(
        policy.get("max_turnover_required_inr") or elig.get("avg_turnover_inr") or 4_000_000
    )
    min_days = int(policy.get("min_days_to_deadline") or 7)

    queries = list(keywords.get("gem_queries") or [])
    portals = list(keywords.get("portal_watchlist") or [])

    with GemScout() as gem:
        seen: dict[str, Any] = {}
        for q in queries:
            for t in gem.search(q, pages=pages):
                seen[t.external_id] = t
        console.print(f"GeM listings: [cyan]{len(seen)}[/cyan]")

        # Local keyword rank first to prefer training titles before PDF download
        scored = rank_tenders(list(seen.values()), keywords=keywords, profile=profile)
        ordered = [s.tender for s in scored] or list(seen.values())
        console.print(f"Enriching top [cyan]{min(max_docs, len(ordered))}[/cyan] PDFs…")

        enriched: list[dict[str, Any]] = []
        for i, tender in enumerate(ordered[:max_docs]):
            row = enrich(gem, tender)
            enriched.append(row)
            flag = "NO-EMD" if row.get("no_emd") else f"EMD={row.get('emd_amount')}"
            console.print(
                f"  [{i+1}/{min(max_docs, len(ordered))}] {flag} "
                f"exp={row.get('experience_years_required')} "
                f"turn={row.get('turnover_required_inr')} "
                f"prox={row.get('proximity')} {row.get('bid_number')}"
            )

    fitted = apply_company_filters(
        enriched,
        max_exp=max_exp,
        max_turnover=max_turnover,
        min_days=min_days,
    )

    # Near-misses: no EMD + deadline OK, but exp/turnover (or other) blocks
    near: list[dict[str, Any]] = []
    for r in enriched:
        if r.get("eligible"):
            continue
        if not r.get("no_emd"):
            continue
        end_dt = r.get("end_dt")
        if end_dt is None:
            continue
        if getattr(end_dt, "tzinfo", None) is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        if end_dt < datetime.now(timezone.utc) + timedelta(days=min_days):
            continue
        near.append(r)
    near.sort(key=lambda x: (-int(x.get("proximity") or 0), x.get("end_at") or "9999"))

    # Soft CPPP + watchlist (internet-wide leads; often need manual PDF check)
    cppp_rows: list[dict[str, Any]] = []
    try:
        with CpppScout() as cppp:
            for t in cppp.search_many(list(keywords.get("cppp_queries") or [])[:4]):
                cppp_rows.append(
                    {
                        "bid_number": t.bid_number,
                        "title": t.title,
                        "url": t.url,
                        "source": "cppp",
                        "manual_check": True,
                        "note": "CPPP listing — open link and verify EMD/exp/turnover manually",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]CPPP soft-fail:[/yellow] {exc}")

    watch = probe_watchlist(portals)

    return {
        "profile": {
            "home": f"{profile.get('company', {}).get('home_city')}, {profile.get('company', {}).get('home_state')}",
            "max_experience_years": max_exp,
            "max_turnover_inr": max_turnover,
            "min_days_to_deadline": min_days,
            "prefer_no_emd": True,
        },
        "scanned": len(enriched),
        "matches": fitted,
        "near_misses": near[:25],
        "rejected_sample": [r for r in enriched if not r.get("no_emd")][:8],
        "cppp_leads": cppp_rows[:20],
        "watchlist_leads": watch,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_report(payload: dict[str, Any]) -> Path:
    out = OUTPUT_DIR / "digests"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out / f"ai_train_contractor_fit_{stamp}.json"
    md_path = out / f"ai_train_contractor_fit_{stamp}.md"

    # JSON without datetime objects
    serializable = json.loads(
        json.dumps(
            payload,
            default=lambda o: o.isoformat() if isinstance(o, datetime) else str(o),
        )
    )
    json_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    matches = payload.get("matches") or []
    near = payload.get("near_misses") or []
    lines = [
        "# AI Training Contractor Fit — Pathankot filters",
        f"_Generated: {payload.get('generated_at')}_",
        "",
        "## Your constraints",
        f"- Home: **{payload['profile']['home']}**",
        f"- No EMD / EMD exempt only",
        f"- Deadline ≥ **{payload['profile']['min_days_to_deadline']} days**",
        f"- Experience required ≤ **{payload['profile']['max_experience_years']} years**",
        f"- Turnover required ≤ **₹{payload['profile']['max_turnover_inr']:,.0f}** (40 lakh)",
        "",
        f"## Matches ({len(matches)})",
        "",
    ]
    if not matches:
        lines.append(
            "_No GeM bids passed all filters in this scan. "
            "See near-misses and watchlist/CPPP leads below._"
        )
    for i, r in enumerate(matches, 1):
        lines += [
            f"### {i}. [prox {r.get('proximity')}] {r.get('bid_number')}",
            f"- **Title:** {r.get('title')}",
            f"- **Buyer:** {r.get('ministry')} / {r.get('department')}",
            f"- **EMD:** {r.get('emd_amount')} — {r.get('emd_evidence')}",
            f"- **Experience req:** {r.get('experience_years_required')} — {r.get('experience_evidence')}",
            f"- **Turnover req:** {r.get('turnover_required_inr')} — {r.get('turnover_evidence')}",
            f"- **Location:** states={r.get('states')} cities={r.get('cities')}",
            f"- **Deadline:** {r.get('end_at')}",
            f"- **Link:** {r.get('url')}",
            f"- **Notes:** {'; '.join(r.get('notes') or []) or '—'}",
            "",
        ]

    lines += [
        "",
        f"## Near-misses — no EMD + ≥7d left, but blocked ({len(near)})",
        "_Usually experience > 2y or turnover > 40L._",
        "",
    ]
    if not near:
        lines.append("_None in this scan._")
    for i, r in enumerate(near, 1):
        lines += [
            f"### NM{i}. [prox {r.get('proximity')}] {r.get('bid_number')}",
            f"- **Title:** {r.get('title')}",
            f"- **Blocked:** {'; '.join(r.get('reasons') or [])}",
            f"- **Exp / TO:** {r.get('experience_years_required')}y / {r.get('turnover_required_inr')}",
            f"- **Deadline:** {r.get('end_at')}",
            f"- **Link:** {r.get('url')}",
            "",
        ]

    lines += ["## Internet watchlist (manual follow-up)", ""]
    for w in payload.get("watchlist_leads") or []:
        lines.append(
            f"- **{w.get('name')}** — {w.get('url')} "
            f"(hits={w.get('keyword_hits') or w.get('error')})"
        )
    lines += ["", "## CPPP soft leads", ""]
    for c in payload.get("cppp_leads") or []:
        lines.append(f"- {c.get('bid_number')}: {c.get('title')[:100]} — {c.get('url')}")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"Saved [green]{md_path}[/green]")
    return md_path


def print_table(matches: list[dict[str, Any]]) -> None:
    table = Table(title="Eligible AI-training bids (no EMD, ≤2y exp, ≤40L TO, ≥7d left)")
    table.add_column("Prox", justify="right")
    table.add_column("Bid")
    table.add_column("Exp")
    table.add_column("TO")
    table.add_column("Where")
    table.add_column("End")
    table.add_column("Title")
    for r in matches:
        where = ",".join((r.get("cities") or [])[:2] or (r.get("states") or [])[:2] or ["?"])
        to = r.get("turnover_required_inr")
        to_s = "—" if to is None else f"{to/100000:.1f}L"
        exp = r.get("experience_years_required")
        table.add_row(
            str(r.get("proximity") or 0),
            str(r.get("bid_number") or ""),
            "—" if exp is None else str(exp),
            to_s,
            where,
            (r.get("end_at") or "")[:10],
            str(r.get("title") or "")[:45],
        )
    console.print(table)
