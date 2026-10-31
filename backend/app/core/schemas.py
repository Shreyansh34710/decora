from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator


DecisionStatus = Literal["accepted", "rejected", "unresolved", "contested"]
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
    supports_claim: Optional[bool] = Field(
        default=None,
        description="Model assessment only; None means unknown. Quote verification does not verify logical support.",
    )


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
    title: str = Field(default="Untitled discussion", max_length=200)
    source_reference: Optional[str] = Field(default=None, max_length=2000)
    text: str = Field(..., min_length=20)


class StoredDecision(BaseModel):
    id: str
    proposal: str
    status: DecisionStatus
    reason: Optional[str] = None
    outcome_basis: OutcomeBasis = "unknown"
    evidence: List[Evidence] = Field(default_factory=list)
    outcome_evidence: List[Evidence] = Field(default_factory=list)
    rejection_reasons: List[RejectionReason] = Field(default_factory=list)
    history: List[dict] = Field(default_factory=list)
    verified: bool = False
    source_title: str
    source_reference: Optional[str] = None
    source_repository: Optional[str] = None
    source_timestamps: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class HistoricalProposal(BaseModel):
    proposal: str = Field(..., min_length=1, max_length=300)
    status: Optional[DecisionStatus] = None

    @field_validator("proposal")
    @classmethod
    def proposal_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("proposal must contain non-whitespace text")
        return value


class HistoricalSearchRequest(BaseModel):
    proposals: List[HistoricalProposal] = Field(..., min_length=1, max_length=30)
    source_title: str = Field(default="Untitled discussion", max_length=200)
    source_reference: Optional[str] = Field(default=None, max_length=2000)
    source_text: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=50)


class HistoricalDecision(StoredDecision):
    relevance_score: float
    matched_proposals: List[str] = Field(default_factory=list)
    potential_conflict: bool = False
    conflict_reasons: List[str] = Field(default_factory=list)


class ExtractionResponse(BaseModel):
    discussion_title: str
    model: str
    decisions: List[Alternative]
    total_messages: int
    verified_decisions: int
    unverified_decisions: int
    memory_persisted: bool = True
    memory_decision_ids: List[str] = Field(default_factory=list)
    memory_conflicts: List[str] = Field(default_factory=list)
    historical_decisions: List[HistoricalDecision] = Field(default_factory=list)


GitHubDiscussionKind = Literal["issue", "pull_request"]


class GitHubRepositoryRequest(BaseModel):
    repository_url: str = Field(..., min_length=1, max_length=500)


class GitHubRepositoryInfo(BaseModel):
    full_name: str
    html_url: str
    description: Optional[str] = None
    default_branch: Optional[str] = None
    stargazers_count: int = 0
    open_issues_count: int = 0


class GitHubDiscussionSummary(BaseModel):
    kind: GitHubDiscussionKind
    number: int
    title: str
    body: Optional[str] = None
    state: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    html_url: str
    comments_count: int = 0
    draft: Optional[bool] = None


class GitHubDiscussionListing(BaseModel):
    repository: GitHubRepositoryInfo
    issues: List[GitHubDiscussionSummary] = Field(default_factory=list)
    pull_requests: List[GitHubDiscussionSummary] = Field(default_factory=list)


class GitHubDiscussionComment(BaseModel):
    id: str
    kind: Literal["issue_comment", "review_comment", "review"]
    author: Optional[str] = None
    body: Optional[str] = None
    created_at: Optional[str] = None
    html_url: Optional[str] = None


class GitHubDiscussionDetail(BaseModel):
    repository: GitHubRepositoryInfo
    discussion: GitHubDiscussionSummary
    comments: List[GitHubDiscussionComment] = Field(default_factory=list)


class GitHubAnalysisRequest(BaseModel):
    repository_url: str = Field(..., min_length=1, max_length=500)
    kind: GitHubDiscussionKind
    number: int = Field(..., ge=1)


class GitHubAnalysisResponse(ExtractionResponse):
    repository: GitHubRepositoryInfo
    discussion: GitHubDiscussionSummary
    imported_messages: int
