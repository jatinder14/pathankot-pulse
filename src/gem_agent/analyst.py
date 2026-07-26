from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import get_settings, load_profile
from .models import AnalysisResult, Decision, Tender


def _heuristic_analysis(tender: Tender, profile: dict[str, Any]) -> AnalysisResult:
    title = tender.title.lower()
    risks: list[str] = []
    notes: list[str] = []
    docs = [
        "Company profile / GeM seller registration proof",
        "GST certificate",
        "Cancelled cheque / bank details",
        "PAN",
        "Experience / work-order copies (if asked)",
        "Team CVs relevant to scope",
        "Technical compliance matrix vs bid specs",
    ]

    softwareish = any(
        k in title
        for k in (
            "software",
            "application",
            "ai",
            "artificial",
            "machine learning",
            "chatbot",
            "training",
            "e-learning",
            "skill",
            "digital",
            "consultancy",
        )
    )
    product_license = any(
        k in title for k in ("upgradation", "license", "licence", "oem", "oracle", "stata", "sap ")
    )

    turnover = int(profile.get("eligibility_defaults", {}).get("avg_turnover_inr") or 0)
    skip_above = int(
        profile.get("bid_policy", {}).get("skip_if_turnover_required_above_inr") or 10_000_000
    )

    if product_license and "custom" not in title:
        decision = Decision.NO_GO
        notes.append("Looks like packaged/OEM software supply rather than custom build/training.")
        risks.append("May require OEM authorization you may not have.")
    elif softwareish:
        decision = Decision.GO if turnover > 0 else Decision.MAYBE
        notes.append("Aligns with software / AI / training capability profile.")
        if turnover <= 0:
            notes.append("Update avg_turnover_inr in profile.yaml for stronger eligibility checks.")
    else:
        decision = Decision.MAYBE
        notes.append("Partial keyword match — review bid PDF before investing time.")

    if skip_above and turnover and turnover < 500_000:
        risks.append("Low declared turnover may fail many GeM service eligibility gates.")

    approach = (
        "Map bid scope to your custom software / AI / training offerings. "
        "Prepare a compliance matrix, cite past projects, and propose a phased delivery plan "
        "with training handoff if the buyer is a government department."
    )

    summary = (
        f"{tender.bid_number}: {tender.title}. "
        f"Buyer: {tender.ministry or 'N/A'} / {tender.department or 'N/A'}. "
        f"Heuristic decision: {decision.value}."
    )

    return AnalysisResult(
        decision=decision,
        summary=summary,
        eligibility_notes=notes,
        risks=risks,
        required_docs=docs,
        suggested_approach=approach,
        confidence=0.55 if softwareish else 0.35,
        used_llm=False,
    )


def _llm_analysis(tender: Tender, profile: dict[str, Any]) -> AnalysisResult | None:
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    prompt = {
        "role": "You are a government tender analyst for an Indian IT / AI / training MSME.",
        "tender": tender.model_dump(mode="json"),
        "company_profile": profile,
        "instructions": (
            "Return ONLY JSON with keys: decision (go|maybe|no_go), summary, "
            "eligibility_notes (array), risks (array), required_docs (array), "
            "suggested_approach (string), confidence (0-1)."
        ),
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "temperature": 0.2,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You analyse GeM/CPPP tenders. Be strict on OEM/product-only bids.",
                        },
                        {"role": "user", "content": json.dumps(prompt)},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
    except Exception:
        return None

    decision_raw = str(data.get("decision", "maybe")).lower().replace("-", "_")
    if decision_raw not in {d.value for d in Decision}:
        decision_raw = Decision.MAYBE.value

    return AnalysisResult(
        decision=Decision(decision_raw),
        summary=str(data.get("summary") or ""),
        eligibility_notes=list(data.get("eligibility_notes") or []),
        risks=list(data.get("risks") or []),
        required_docs=list(data.get("required_docs") or []),
        suggested_approach=str(data.get("suggested_approach") or ""),
        confidence=float(data.get("confidence") or 0.6),
        used_llm=True,
    )


def analyze_tender(tender: Tender, profile: dict[str, Any] | None = None) -> AnalysisResult:
    profile = profile or load_profile()
    llm = _llm_analysis(tender, profile)
    if llm:
        return llm
    return _heuristic_analysis(tender, profile)


def extract_text_hints_from_pdf(path: str, max_chars: int = 8000) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(path)
    chunks: list[str] = []
    for page in reader.pages[:12]:
        chunks.append(page.extract_text() or "")
        if sum(len(c) for c in chunks) >= max_chars:
            break
    text = "\n".join(chunks)
    return text[:max_chars]


def enrich_with_document_text(tender: Tender, text: str, profile: dict[str, Any] | None = None) -> AnalysisResult:
    """Re-run analysis with optional bid document text attached to raw."""
    enriched = tender.model_copy(deep=True)
    enriched.raw = {**enriched.raw, "document_text_excerpt": text[:6000]}
    # Lightweight keyword eligibility cues from PDF text
    result = analyze_tender(enriched, profile)
    if re.search(r"average annual turnover|minimum.*?turnover", text, re.I):
        result.eligibility_notes.append("Document mentions turnover requirements — verify against profile.")
        result.risks.append("Turnover clause detected in bid document.")
    if re.search(r"OEM|manufacturer authorization|MAF", text, re.I):
        result.risks.append("OEM / manufacturer authorization language detected.")
        if result.decision == Decision.GO:
            result.decision = Decision.MAYBE
    return result
