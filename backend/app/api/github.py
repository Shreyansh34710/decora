import json
import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query

from app.core.schemas import (
    GitHubAnalysisRequest, GitHubAnalysisResponse,
    GitHubDiscussionDetail, GitHubDiscussionKind, GitHubDiscussionListing,
    GitHubRepositoryInfo,
)
from app.services.extractor import DecisionExtractor
from app.services.github import GitHubIntegrationError, GitHubService
from app.services.memory import get_memory_store


router = APIRouter()
logger = logging.getLogger(__name__)


def _raise_github_error(error: GitHubIntegrationError):
    headers = {"Retry-After": error.retry_after} if error.retry_after else None
    raise HTTPException(status_code=error.status_code, detail=error.detail, headers=headers)


@router.get("/github/repository", response_model=GitHubRepositoryInfo)
def github_repository(repository_url: str = Query(..., min_length=1, max_length=500)):
    try:
        with GitHubService() as service:
            return service.repository_info(repository_url)
    except GitHubIntegrationError as error:
        _raise_github_error(error)


@router.get("/github/discussions", response_model=GitHubDiscussionListing)
def github_discussions(repository_url: str = Query(..., min_length=1, max_length=500)):
    try:
        with GitHubService() as service:
            return service.list_discussions(repository_url)
    except GitHubIntegrationError as error:
        _raise_github_error(error)


@router.get("/github/discussions/{kind}/{number}", response_model=GitHubDiscussionDetail)
def github_discussion(
    kind: GitHubDiscussionKind,
    number: int,
    repository_url: str = Query(..., min_length=1, max_length=500),
):
    if number < 1:
        raise HTTPException(status_code=422, detail="Discussion number must be positive.")
    try:
        with GitHubService() as service:
            return service.get_discussion(repository_url, kind, number)
    except GitHubIntegrationError as error:
        _raise_github_error(error)


@router.post("/github/analyze", response_model=GitHubAnalysisResponse)
def analyze_github_discussion(request: GitHubAnalysisRequest):
    try:
        with GitHubService() as service:
            detail = service.get_discussion(request.repository_url, request.kind, request.number)
            messages = service.to_messages(detail)
            if not messages:
                raise HTTPException(status_code=422, detail="This discussion contains no importable message text.")

        extractor = DecisionExtractor()
        decisions = extractor.extract(messages)
        source_title = "{} — {} #{}: {}".format(
            detail.repository.full_name,
            "Pull request" if request.kind == "pull_request" else "Issue",
            detail.discussion.number,
            detail.discussion.title,
        )
        source_text = json.dumps(
            [message.model_dump(mode="json") for message in messages],
            ensure_ascii=False, separators=(",", ":"),
        )
        try:
            memory = get_memory_store()
            saved = memory.save(
                title=source_title,
                source_reference=detail.discussion.html_url,
                source_repository=detail.repository.html_url,
                source_text=source_text,
                decisions=decisions,
            )
            historical = memory.find_related(
                proposals=[{"proposal": decision.proposal, "status": decision.status}
                           for decision in decisions],
                source_title=source_title,
                source_reference=detail.discussion.html_url,
                source_text=source_text,
            )
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail="Analysis completed, but decision memory could not be saved.",
            ) from error

        verified = sum(1 for decision in decisions if decision.verified)
        return GitHubAnalysisResponse(
            discussion_title=source_title,
            model=getattr(extractor.provider, "model", "unknown"),
            decisions=decisions,
            total_messages=len(messages),
            verified_decisions=verified,
            unverified_decisions=len(decisions) - verified,
            memory_persisted=saved["persisted"],
            memory_decision_ids=saved["decision_ids"],
            memory_conflicts=saved["conflicts"],
            historical_decisions=historical,
            repository=detail.repository,
            discussion=detail.discussion,
            imported_messages=len(messages),
        )
    except GitHubIntegrationError as error:
        _raise_github_error(error)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error analyzing GitHub discussion")
        raise HTTPException(
            status_code=500,
            detail="GitHub discussion analysis failed due to an unexpected server error.",
        )
