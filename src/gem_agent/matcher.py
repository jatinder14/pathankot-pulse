from __future__ import annotations

import re
from typing import Any

from .models import ScoredTender, Tender


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _contains_keyword(hay: str, keyword: str) -> bool:
    """Match multi-word phrases as substrings; short tokens with word boundaries."""
    kw = _norm(keyword)
    if not kw:
        return False
    if " " in kw or "-" in kw or len(kw) >= 4:
        return kw in hay
    return re.search(rf"\b{re.escape(kw)}\b", hay) is not None


def score_tender(
    tender: Tender,
    *,
    include_any: list[str],
    exclude_any: list[str],
    profile: dict[str, Any],
) -> ScoredTender | None:
    # Match include keywords on title only (ministry names like
    # "Skill Development" / "Information Technology" create false positives).
    title_hay = _norm(tender.title)

    for bad in exclude_any:
        if _contains_keyword(title_hay, bad):
            return None

    matched = [kw for kw in include_any if _contains_keyword(title_hay, kw)]
    if not matched:
        return None

    score = min(1.0, 0.35 + 0.08 * len(matched))
    reasons = [f"Matched keywords: {', '.join(matched[:8])}"]

    boosts = (
        profile.get("bid_policy", {}).get("preferred_keywords_boost")
        or []
    )
    boost_hits = [b for b in boosts if _contains_keyword(title_hay, b)]
    if boost_hits:
        score = min(1.0, score + 0.05 * len(boost_hits))
        reasons.append(f"Capability boost: {', '.join(boost_hits[:5])}")

    caps = " ".join(profile.get("capabilities") or []).lower()
    for token in ("software", "training", "artificial intelligence", "ai", "e-learning"):
        if _contains_keyword(title_hay, token) and token in caps:
            score = min(1.0, score + 0.04)

    if tender.end_at:
        reasons.append(f"Deadline: {tender.end_at.isoformat()}")

    return ScoredTender(
        tender=tender,
        fit_score=round(score, 3),
        matched_keywords=matched,
        reasons=reasons,
    )


def rank_tenders(
    tenders: list[Tender],
    *,
    keywords: dict[str, Any],
    profile: dict[str, Any],
) -> list[ScoredTender]:
    include_any = list(keywords.get("include_any") or [])
    exclude_any = list(keywords.get("exclude_any") or [])
    scored: list[ScoredTender] = []
    for tender in tenders:
        item = score_tender(
            tender,
            include_any=include_any,
            exclude_any=exclude_any,
            profile=profile,
        )
        if item:
            scored.append(item)
    scored.sort(key=lambda s: (-s.fit_score, s.tender.end_at or s.tender.title))
    return scored
