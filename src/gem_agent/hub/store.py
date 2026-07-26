"""Shared lead model + JSON store for Pathankot Pulse hub."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import OUTPUT_DIR, ROOT

HUB_DIR = OUTPUT_DIR / "hub"
LEADS_PATH = HUB_DIR / "leads.json"


@dataclass
class Lead:
    id: str
    portal: str
    section: str
    kind: str  # tenders | auctions | classifieds
    title: str
    url: str
    location: str = ""
    pincode: str = ""
    price: str = ""
    ends_at: str = ""
    starts_at: str = ""
    buyer: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    scraped_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    """UTC ISO timestamp for scrape metadata."""
    return datetime.now(timezone.utc).isoformat()


# Public alias for scrapers
now_iso = _now


def load_hub_config() -> dict[str, Any]:
    import yaml

    path = ROOT / "config" / "hub.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_leads() -> dict[str, Any]:
    if not LEADS_PATH.exists():
        return {"updated_at": None, "by_portal": {}, "region": {}}
    return json.loads(LEADS_PATH.read_text(encoding="utf-8"))


def save_leads(by_portal: dict[str, list[Lead]], *, region: dict[str, Any] | None = None) -> Path:
    HUB_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _now(),
        "region": region or load_hub_config().get("region") or {},
        "by_portal": {
            portal: [x.to_dict() if isinstance(x, Lead) else x for x in leads]
            for portal, leads in by_portal.items()
        },
        "counts": {p: len(v) for p, v in by_portal.items()},
    }
    LEADS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (HUB_DIR / f"leads_{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return LEADS_PATH
