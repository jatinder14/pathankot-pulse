from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PROPOSALS_DIR, load_profile
from .models import AnalysisResult, ProposalDraft, Tender


def draft_proposal(
    tender: Tender,
    analysis: AnalysisResult,
    *,
    profile: dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> ProposalDraft:
    profile = profile or load_profile()
    output_dir = output_dir or PROPOSALS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    company = profile.get("company", {})
    caps = profile.get("capabilities") or []
    projects = profile.get("past_projects") or []
    training = profile.get("training_offerings") or []
    stack = profile.get("tech_stack") or []

    safe_name = tender.bid_number.replace("/", "_").replace(" ", "_")
    path = output_dir / f"{safe_name}_technical_draft.md"

    lines = [
        f"# Technical Bid Draft — {tender.bid_number}",
        "",
        f"**Title:** {tender.title}",
        f"**Buyer:** {tender.ministry or 'N/A'} / {tender.department or 'N/A'}",
        f"**Portal link:** {tender.url or 'N/A'}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Analyst decision:** {analysis.decision.value} (confidence {analysis.confidence:.2f})",
        "",
        "> This is a DRAFT for human review. Do not submit unchanged without compliance checks.",
        "",
        "## 1. Covering letter summary",
        "",
        f"{company.get('legal_name') or company.get('brand_name') or 'Our organisation'} "
        f"proposes to deliver the scope under **{tender.bid_number}** aligned to government-grade "
        "software engineering, AI enablement, and capacity-building practices.",
        "",
        "## 2. Understanding of requirement",
        "",
        analysis.summary,
        "",
        analysis.suggested_approach,
        "",
        "## 3. Proposed solution approach",
        "",
        "1. Discovery & requirements workshop with buyer stakeholders",
        "2. Solution design (architecture, security, data, accessibility)",
        "3. Agile build / configure / integrate with fortnightly demos",
        "4. UAT, hardening, documentation, and handover",
        "5. Optional training / change-management for department users",
        "",
        "### Capability alignment",
        "",
    ]
    for cap in caps:
        lines.append(f"- {cap}")

    lines += ["", "### Technology stack", ""]
    for item in stack:
        lines.append(f"- {item}")

    lines += ["", "## 4. Relevant experience", ""]
    for project in projects:
        if isinstance(project, dict):
            lines.append(f"- **{project.get('name')}** — {project.get('summary')}")
        else:
            lines.append(f"- {project}")

    if training:
        lines += ["", "## 5. Training / capacity building (if in scope)", ""]
        for item in training:
            lines.append(f"- {item}")

    lines += ["", "## 6. Compliance checklist (to complete before submit)", ""]
    for doc in analysis.required_docs:
        lines.append(f"- [ ] {doc}")

    if analysis.eligibility_notes:
        lines += ["", "## 7. Eligibility notes", ""]
        for note in analysis.eligibility_notes:
            lines.append(f"- {note}")

    if analysis.risks:
        lines += ["", "## 8. Risks / red flags", ""]
        for risk in analysis.risks:
            lines.append(f"- {risk}")

    lines += [
        "",
        "## 9. Commercial placeholder",
        "",
        "- Proposed commercial model: milestone-based / L1-aware quote (fill after BOQ review)",
        f"- Internal floor margin policy: {profile.get('bid_policy', {}).get('min_margin_pct', 18)}%",
        f"- Max bid value policy: INR {profile.get('company', {}).get('max_bid_value_inr', 'N/A')}",
        "",
        "## 10. Declaration",
        "",
        "We confirm willingness to comply with GeM / tender terms subject to final legal review.",
        "",
    ]

    markdown = "\n".join(lines)
    path.write_text(markdown, encoding="utf-8")

    return ProposalDraft(
        bid_number=tender.bid_number,
        title=tender.title,
        markdown=markdown,
        path=str(path),
    )
