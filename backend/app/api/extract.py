
import sqlite3

from fastapi import APIRouter, HTTPException

from app.core.schemas import DiscussionRequest, ExtractionResponse
from app.services.parser import parse_discussion
from app.services.extractor import DecisionExtractor
from app.services.memory import get_memory_store


router = APIRouter()


@router.post("/extract", response_model=ExtractionResponse)
def extract_discussion(request: DiscussionRequest):

    try:
        messages = parse_discussion(request.text)

        if not messages:
            raise HTTPException(
                status_code=400,
                detail="No discussion messages could be parsed."
            )

        extractor = DecisionExtractor()
        decisions = extractor.extract(messages)

        try:
            memory_store = get_memory_store()
            memory_result = memory_store.save(
                title=request.title,
                source_reference=request.source_reference,
                source_text=request.text,
                decisions=decisions,
            )
            historical_decisions = memory_store.find_related(
                proposals=[{"proposal": decision.proposal, "status": decision.status}
                           for decision in decisions],
                source_title=request.title,
                source_reference=request.source_reference,
                source_text=request.text,
            )
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail="Analysis completed, but decision memory could not be saved.",
            ) from error

        verified = sum(
            1 for decision in decisions if decision.verified
        )

        return ExtractionResponse(
            discussion_title=request.title,
            model=getattr(extractor.provider, "model", "unknown"),
            decisions=decisions,
            total_messages=len(messages),
            verified_decisions=verified,
            unverified_decisions=len(decisions) - verified,
            memory_persisted=memory_result["persisted"],
            memory_decision_ids=memory_result["decision_ids"],
            memory_conflicts=memory_result["conflicts"],
            historical_decisions=historical_decisions,
        )

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Extraction failed: {}".format(str(error))
        )
