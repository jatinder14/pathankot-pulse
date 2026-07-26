"""Run all Pathankot Pulse scrapers and preference recommendations."""

from __future__ import annotations

from typing import Any, Callable

from rich.console import Console

from .recommend import build_apply_recommendations
from .scrapers import (
    scrape_bank_auctions,
    scrape_cppp,
    scrape_gem,
    scrape_gov_auctions,
    scrape_olx,
    scrape_punjab,
    scrape_vehicles,
)
from .store import Lead, load_hub_config, load_leads, save_leads
from .tendersplus import scrape_tendersplus

console = Console()


def _scrape_tendersplus() -> list[Lead]:
    cfg = load_hub_config()
    tp = cfg.get("tendersplus") or {}
    return scrape_tendersplus(
        keywords=list(tp.get("keywords") or []),
        states=list(tp.get("states") or ["Punjab"]),
        max_pages=int(tp.get("max_pages_per_keyword") or 8),
        year=int(tp.get("year") or 2026),
    )


SCRAPERS: dict[str, Callable[..., list[Lead]]] = {
    "tendersplus": _scrape_tendersplus,
    "gem": lambda: scrape_gem(pages=3),
    "cppp": scrape_cppp,
    "punjab": scrape_punjab,
    "bank_auction": scrape_bank_auctions,
    "gov_auction": scrape_gov_auctions,
    "vehicles": scrape_vehicles,
    "olx": scrape_olx,
}


def run_hub_scrape(
    *,
    portals: list[str] | None = None,
    with_recommendations: bool = True,
    fit_pages: int = 2,
    fit_max_docs: int = 30,
) -> dict[str, Any]:
    cfg = load_hub_config()
    enabled = {
        p["id"]
        for p in (cfg.get("portals") or [])
        if p.get("enabled", True)
    }
    targets = portals or sorted(enabled & set(SCRAPERS))
    by_portal: dict[str, list[Lead]] = {}
    errors: dict[str, str] = {}

    existing = load_leads().get("by_portal") or {}
    for portal, rows in existing.items():
        if portal not in targets:
            by_portal[portal] = [
                Lead(**{k: v for k, v in row.items() if k in Lead.__dataclass_fields__})
                if isinstance(row, dict)
                else row
                for row in rows
            ]

    for portal in targets:
        fn = SCRAPERS.get(portal)
        if not fn:
            continue
        console.print(f"[cyan]Scraping[/cyan] {portal}…")
        try:
            leads = fn()
            by_portal[portal] = leads
            console.print(f"  → {len(leads)} real leads")
        except Exception as exc:  # noqa: BLE001
            errors[portal] = str(exc)
            by_portal[portal] = []
            console.print(f"  [red]fail[/red] {exc}")

    path = save_leads(by_portal, region=cfg.get("region"))
    rec: dict[str, Any] | None = None
    if with_recommendations and (portals is None or "gem" in targets):
        console.print("[cyan]Building apply recommendations[/cyan] (your preferences)…")
        try:
            rec = build_apply_recommendations(pages=fit_pages, max_docs=fit_max_docs)
            console.print(
                f"  → {len(rec.get('apply') or [])} apply · {len(rec.get('watch') or [])} watch"
            )
        except Exception as exc:  # noqa: BLE001
            errors["recommendations"] = str(exc)
            console.print(f"  [red]recommendations fail[/red] {exc}")

    return {
        "path": str(path),
        "counts": {k: len(v) for k, v in by_portal.items()},
        "errors": errors,
        "region": cfg.get("region"),
        "brand": (cfg.get("owner") or {}).get("brand"),
        "recommendations": {
            "apply": len((rec or {}).get("apply") or []),
            "watch": len((rec or {}).get("watch") or []),
        }
        if rec
        else None,
    }
