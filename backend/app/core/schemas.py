from typing import List, Optional, Literal
from pydantic import BaseModel, Field


DecisionStatus = Literal["accepted", "rejected", "unresolved"]
OutcomeBasis = Literal[
    "explicit_acceptance", "explicit_rejection", "consensus",
    "individual_opinion", "unresolved", "unknown"
]


class Evidence(BaseModel):
    segment_id: str
    quote: str
    author: Optional[str] = None
    timestamp: Optional[str] = None
    source_url: Optional[str] = None
    quote_verified: bool = False
    supports_claim: Optional[bool] = None


class RejectionReason(BaseModel):
    text: str
    evidence: List[Evidence] = Field(default_factory=list)


class Alternative(BaseModel):
    decision_id: str
    proposal: str
    status: DecisionStatus
    reason: Optional[str] = None
    outcome_basis: OutcomeBasis = "unknown"
    evidence: List[Evidence] = Field(default_factory=list)
    outcome_evidence: List[Evidence] = Field(default_factory=list)
    rejection_reasons: List[RejectionReason] = Field(default_factory=list)
    history: List[dict] = Field(default_factory=list)
    verified: bool = False


class DiscussionMessage(BaseModel):
    message_id: str
    author: Optional[str] = None
    timestamp: Optional[str] = None
    content: str
    source_url: Optional[str] = None


class DiscussionRequest(BaseModel):
    title: str = "Untitled discussion"
    text: str = Field(..., min_length=20)


class ExtractionResponse(BaseModel):
    discussion_title: str
    model: str
    decisions: List[Alternative]
    total_messages: int
    verified_decisions: int
    unverified_decisions: int
