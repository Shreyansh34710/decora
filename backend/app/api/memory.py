import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.schemas import HistoricalDecision, HistoricalSearchRequest, StoredDecision
from app.services.memory import get_memory_store


router = APIRouter()


def _fetch(query: Optional[str] = None, limit: int = 50, offset: int = 0):
    try:
        return get_memory_store().list_decisions(query=query, limit=limit, offset=offset)
    except (sqlite3.Error, OSError) as error:
        raise HTTPException(status_code=503, detail="Decision memory is unavailable.") from error


@router.get("/memory", response_model=List[StoredDecision])
def list_memory(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _fetch(limit=limit, offset=offset)


@router.get("/memory/search", response_model=List[StoredDecision])
def search_memory(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _fetch(query=q, limit=limit, offset=offset)


@router.post("/memory/related", response_model=List[HistoricalDecision])
def related_memory(request: HistoricalSearchRequest):
    try:
        return get_memory_store().find_related(
            proposals=request.proposals,
            source_title=request.source_title,
            source_reference=request.source_reference,
            source_text=request.source_text,
            limit=request.limit,
        )
    except (sqlite3.Error, OSError) as error:
        raise HTTPException(status_code=503, detail="Decision memory is unavailable.") from error
