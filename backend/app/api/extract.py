
from fastapi import APIRouter, HTTPException

from app.core.schemas import DiscussionRequest, ExtractionResponse
from app.services.parser import parse_discussion
from app.services.extractor import DecisionExtractor


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

        verified = sum(
            1 for decision in decisions if decision.verified
        )

        return ExtractionResponse(
            discussion_title=request.title,
            model=getattr(extractor.provider, "model", "unknown"),
            decisions=decisions,
            total_messages=len(messages),
            verified_decisions=verified,
            unverified_decisions=len(decisions) - verified
        )

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Extraction failed: {}".format(str(error))
        )
