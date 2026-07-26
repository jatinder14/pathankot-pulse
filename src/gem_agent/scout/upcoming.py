"""GeM tenders closing in the next N days (AI / training keyword filter)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from ..config import OUTPUT_DIR, get_settings, load_keywords
from .gem import GemScout

console = Console()


def run_upcoming_closing_scout(
    *,
    days: int = 7,
    pages: int = 2,
) -> dict[str, Any]:
    """List training/AI-related GeM bids whose bid end date falls in [today, today+days]."""
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=max(1, days))
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
    for t in seen.values():
        if not t.end_at:
            continue
        end = t.end_at if t.end_at.tzinfo else t.end_at.replace(tzinfo=timezone.utc)
        if not (now.date() <= end.date() <= window_end.date()):
            continue
        title = (t.title or "").lower()
        if exclude and any(x in title for x in exclude):
            continue
        if include and not any(x in title for x in include):
            continue
        days_left = (end.date() - now.date()).days
        rows.append(
            {
                "bid_number": t.bid_number,
                "external_id": t.external_id,
                "title": t.title,
                "ministry": t.ministry,
                "department": t.department,
                "end_at": end.isoformat(),
                "days_left": days_left,
                "url": t.url,
                "source": t.source,
            }
        )

    rows.sort(key=lambda r: (r.get("end_at") or "9999", r.get("bid_number") or ""))
    return {
        "window_start": now.date().isoformat(),
        "window_end": window_end.date().isoformat(),
        "days": days,
        "listings_scanned": len(seen),
        "count": len(rows),
        "tenders": rows,
        "generated_at": now.isoformat(),
    }


def save_upcoming_report(payload: dict[str, Any]) -> Path:
    out = OUTPUT_DIR / "digests"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = out / f"upcoming_closing_{stamp}.json"
    md_path = out / f"upcoming_closing_{stamp}.md"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        f"# Tenders closing next {payload.get('days')} days",
        f"_Window: {payload.get('window_start')} → {payload.get('window_end')}_",
        f"_Generated: {payload.get('generated_at')}_",
        "",
        f"Found **{payload.get('count', 0)}** (scanned {payload.get('listings_scanned', 0)} listings).",
        "",
    ]
    for i, r in enumerate(payload.get("tenders") or [], 1):
        lines += [
            f"### {i}. [{r.get('days_left')}d] {r.get('bid_number')}",
            f"- **Ends:** {r.get('end_at')}",
            f"- **Title:** {r.get('title')}",
            f"- **Buyer:** {r.get('ministry')} / {r.get('department')}",
            f"- **Link:** {r.get('url')}",
            "",
        ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    console.print(f"Saved [green]{md_path}[/green]")
    return md_path
