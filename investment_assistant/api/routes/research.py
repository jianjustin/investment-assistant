from datetime import date

from fastapi import APIRouter, HTTPException

from investment_assistant.services import research

router = APIRouter()


@router.get("/api/research/event-study/kinds")
def kinds():
    return research.available_kinds()


@router.get("/api/research/event-study")
def event_study(kind: str | None = None, since: str | None = None, asof: str | None = None):
    if not kind:
        raise HTTPException(status_code=400, detail="kind is required")
    return research.event_study_view(
        kind,
        since=date.fromisoformat(since) if since else None,
        asof=date.fromisoformat(asof) if asof else None,
    )
