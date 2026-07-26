from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class BidSource(str, Enum):
    GEM = "gem"
    CPPP = "cppp"
    MANUAL = "manual"


class Decision(str, Enum):
    GO = "go"
    MAYBE = "maybe"
    NO_GO = "no_go"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"


class Tender(BaseModel):
    external_id: str
    source: BidSource
    bid_number: str
    title: str
    ministry: str | None = None
    department: str | None = None
    quantity: int | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    url: str | None = None
    document_url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class ScoredTender(BaseModel):
    tender: Tender
    fit_score: float
    matched_keywords: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    decision: Decision
    summary: str
    eligibility_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    required_docs: list[str] = Field(default_factory=list)
    suggested_approach: str = ""
    confidence: float = 0.5
    used_llm: bool = False


class ProposalDraft(BaseModel):
    bid_number: str
    title: str
    markdown: str
    path: str | None = None
