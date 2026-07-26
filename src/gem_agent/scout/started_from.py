"""GeM tenders with bid start date >= today (no end-date window)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from ..config import OUTPUT_DIR, get_settings, load_keywords
from .gem import GemScout

console = Console()


def run_started_from_scout(
    *,
    start_on_or_after: datetime | None = None,
    pages: int = 3,
) -> dict[str, Any]:
    """List keyword-matched GeM bids whose start_at date is >= start_on_or_after (default: today).

    No end-date filter — closing tomorrow or in months both included.
    """
    now = datetime.now(timezone.utc)
    floor = start_on_or_after or now
    if floor.tzinfo is None:
        floor = floor.replace(tzinfo=timezone.utc)
    floor_date = floor.astimezone(timezone.utc).date()

    settings = get_settings()
    keywords = load_keywords(settings)
    queries = list(keywords.get("gem_queries") or [])
    include = [x.lower() for x in (keywords.get("include_any") or [])]
    exclude = [x.lower() for x in (keywords.get("exclude_any") or [])]

    seen: dict[str, Any] = {}
    with GemScout() as gem:
        for q in queries:
            for t in gem.search(q, pages=pages):
                seen[t.external_id] = t

    rows: list[dict[str, Any]] = []
    missing_start = 0
    for t in seen.values():
        if not t.start_at:
            missing_start += 1
            continue
        start = t.start_at if t.start_at.tzinfo else t.start_at.replace(tzinfo=timezone.utc)
        if start.date() < floor_date:
            continue
        title = (t.title or "").lower()
        if exclude and any(x in title for x in exclude):
            continue
        if include and not any(x in title for x in include):
            continue
        end = t.end_at
        if end and not end.tzinfo:
            end = end.replace(tzinfo=timezone.utc)
        days_left = (end.date() - now.date()).days if end else None
        rows.append(
            {
                "bid_number": t.bid_number,
                "external_id": t.external_id,
                "title": t.title,
                "ministry": t.ministry,
                "department": t.department,
                "start_at": start.isoformat(),
                "end_at": end.isoformat() if end else None,
                "days_left": days_left,
                "url": t.url,
                "source": t.source,
            }
        )

    rows.sort(key=lambda r: (r.get("start_at") or "", r.get("bid_number") or ""), reverse=True)
    return {
        "filter": "start_at >= floor; no end-date cutoff",
        "start_on_or_after": floor_date.isoformat(),
        "listings_scanned": len(seen),
        "missing_start_at": missing_start,
        "count": len(rows),
        "tenders": rows,
        "generated_at": now.isoformat(),
    }


def save_started_from_report(payload: dict[str, Any]) -> Path:
    out = OUTPUT_DIR / "digests"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out / f"started_from_{stamp}.json"
    md_path = out / f"started_from_{stamp}.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Tenders with start date ≥ {payload.get('start_on_or_after')}",
        f"_No end-date filter · {payload.get('filter')}_",
        f"_Generated: {payload.get('generated_at')}_",
        "",
        f"Found **{payload.get('count', 0)}** "
        f"(scanned {payload.get('listings_scanned', 0)}; "
        f"missing start_at={payload.get('missing_start_at', 0)}).",
        "",
    ]
    for i, r in enumerate(payload.get("tenders") or [], 1):
        lines += [
            f"### {i}. {r.get('bid_number')}",
            f"- **Starts:** {r.get('start_at')}",
            f"- **Ends:** {r.get('end_at')} ({r.get('days_left')}d left)"
            if r.get("end_at")
            else "- **Ends:** (unknown)",
            f"- **Title:** {r.get('title')}",
            f"- **Buyer:** {r.get('ministry')} / {r.get('department')}",
            f"- **Link:** {r.get('url')}",
            "",
        ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"Saved [green]{md_path}[/green]")
    return md_path
