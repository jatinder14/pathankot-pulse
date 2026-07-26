"""Preference-ranked 'apply these' recommendations for JR Consulting / Pathankot Pulse."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..config import OUTPUT_DIR, load_profile
from ..scout.contractor_fit import run_contractor_fit_scout
from .store import HUB_DIR, Lead, _now, load_hub_config, load_leads


TRAINING_HINTS = (
    "training",
    "capacity building",
    "digital literacy",
    "skill",
    "workshop",
    "faculty",
    "teacher",
    "e-learning",
    "elearning",
    "computer",
    "artificial intelligence",
    " genai",
    "prompt",
    "vocational",
    "literacy",
)


def _is_trainingish(title: str) -> bool:
    t = f" {(title or '').lower()} "
    return any(h in t for h in TRAINING_HINTS)


def build_apply_recommendations(*, pages: int = 2, max_docs: int = 35) -> dict[str, Any]:
    """Run contractor-fit (EMD/exp/TO/deadline/Pathankot) and return apply-ready cards."""
    profile = load_profile()
    company = profile.get("company") or {}
    policy = profile.get("bid_policy") or {}
    hub = load_hub_config()

    fit = run_contractor_fit_scout(pages=pages, max_docs=max_docs)
    matches = fit.get("matches") or []
    near = fit.get("near_misses") or []

    apply: list[dict[str, Any]] = []
    for m in matches:
        title = m.get("title") or ""
        prox = int(m.get("proximity") or 0)
        why: list[str] = []
        if m.get("no_emd") or m.get("emd_ok"):
            why.append("No / exempt EMD")
        if m.get("experience_years_required") is not None:
            why.append(f"Exp ≤{m.get('experience_years_required')}y")
        if m.get("turnover_required_inr") is not None:
            to_l = (m.get("turnover_required_inr") or 0) / 100000
            why.append(f"TO ≤₹{to_l:.0f}L")
        if prox >= 50:
            why.append("Near Pathankot")
        elif prox >= 20:
            why.append("Punjab / nearby state")
        if _is_trainingish(title):
            why.append("Training / digital literacy fit")

        verdict = "APPLY"
        if not _is_trainingish(title):
            verdict = "REVIEW"
            why.append("Confirm ATC subject before bidding")

        apply.append(
            {
                "id": m.get("bid_number") or m.get("external_id") or m.get("url"),
                "portal": "gem",
                "verdict": verdict,
                "score": prox + (25 if _is_trainingish(title) else 0) + (15 if m.get("no_emd") else 0),
                "title": title,
                "url": m.get("url") or "",
                "bid_number": m.get("bid_number"),
                "buyer": " / ".join(
                    x for x in [m.get("ministry"), m.get("department")] if x
                ),
                "location": ", ".join(
                    (m.get("cities") or [])[:2] or (m.get("states") or [])[:2] or ["India"]
                ),
                "ends_at": (str(m.get("end_at") or ""))[:19],
                "experience_years_required": m.get("experience_years_required"),
                "turnover_required_inr": m.get("turnover_required_inr"),
                "emd_ok": bool(m.get("no_emd") or m.get("emd_ok")),
                "proximity": prox,
                "why": why,
                "preferences": {
                    "prefer_no_emd": policy.get("prefer_no_emd", True),
                    "max_experience_years": policy.get("max_experience_years_required", 2),
                    "max_turnover_inr": policy.get("max_turnover_required_inr", 4000000),
                    "home": f"{company.get('home_city')}, {company.get('home_state')}",
                },
            }
        )

    # Near-misses: no EMD + deadline OK, but exp/TO blocks — still show honestly
    for m in near[:12]:
        title = m.get("title") or ""
        if not _is_trainingish(title) and int(m.get("proximity") or 0) < 20:
            continue
        blockers: list[str] = []
        exp = m.get("experience_years_required")
        if exp is not None and exp > float(policy.get("max_experience_years_required") or 2):
            blockers.append(f"Needs {exp}y exp (you: ≤2)")
        to = m.get("turnover_required_inr")
        max_to = float(policy.get("max_turnover_required_inr") or 4_000_000)
        if to is not None and to > max_to:
            blockers.append(f"Needs ₹{to/100000:.0f}L TO (you: ≤₹40L)")
        if not blockers:
            blockers = list(m.get("reasons") or ["Close but not a full match"])
        apply.append(
            {
                "id": m.get("bid_number") or m.get("external_id") or m.get("url"),
                "portal": "gem",
                "verdict": "SKIP",
                "score": int(m.get("proximity") or 0) + (10 if _is_trainingish(title) else 0),
                "title": title,
                "url": m.get("url") or "",
                "bid_number": m.get("bid_number"),
                "buyer": " / ".join(
                    x for x in [m.get("ministry"), m.get("department")] if x
                ),
                "location": ", ".join(
                    (m.get("cities") or [])[:2] or (m.get("states") or [])[:2] or ["India"]
                ),
                "ends_at": (str(m.get("end_at") or ""))[:19],
                "why": ["No EMD"] + blockers + (["Training-ish title"] if _is_trainingish(title) else []),
                "emd_ok": True,
                "proximity": int(m.get("proximity") or 0),
            }
        )

    apply.sort(key=lambda r: (
        {"APPLY": 0, "REVIEW": 1, "SKIP": 2, "WATCH": 3}.get(r.get("verdict"), 9),
        -int(r.get("score") or 0),
        r.get("ends_at") or "9999",
    ))

    # Soft leads from hub store (real scraped tenders only) that look training-related
    soft: list[dict[str, Any]] = []
    store = load_leads()
    for portal, rows in (store.get("by_portal") or {}).items():
        if portal not in {"gem", "cppp", "punjab", "tendersplus"}:
            continue
        for row in rows:
            if "shortcut" in (row.get("tags") or []):
                continue
            title = row.get("title") or ""
            if not _is_trainingish(title):
                continue
            soft.append(
                {
                    "id": row.get("id"),
                    "portal": portal,
                    "verdict": "WATCH",
                    "score": 10,
                    "title": title,
                    "url": row.get("url") or "",
                    "buyer": row.get("buyer") or "",
                    "location": row.get("location") or "",
                    "ends_at": row.get("ends_at") or "",
                    "why": ["Keyword match — eligibility not fully verified yet"],
                }
            )

    payload = {
        "updated_at": _now(),
        "company": company.get("brand_name") or company.get("legal_name"),
        "region": hub.get("region"),
        "rules": {
            "prefer_no_emd": policy.get("prefer_no_emd", True),
            "max_experience_years": policy.get("max_experience_years_required", 2),
            "max_turnover_inr": policy.get("max_turnover_required_inr", 4000000),
            "min_days_to_deadline": policy.get("min_days_to_deadline", 7),
            "focus": "CS / AI / digital literacy training for non-tech gov depts",
        },
        "apply": apply,
        "watch": soft[:12],
        "fit_meta": {
            "scanned": fit.get("scanned"),
            "match_count": len(apply),
        },
    }

    HUB_DIR.mkdir(parents=True, exist_ok=True)
    path = HUB_DIR / "recommendations.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (HUB_DIR / f"recommendations_{stamp}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return payload


def load_recommendations() -> dict[str, Any]:
    path = HUB_DIR / "recommendations.json"
    if not path.exists():
        return {"apply": [], "watch": [], "updated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))
