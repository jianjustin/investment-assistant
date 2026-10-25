from datetime import date
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.research import cards
from investment_assistant.research.card_repository import CardConflict
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


@router.get('/api/research/observation-cards/{symbol}')
def get_card(symbol: str):
    return {'card': cards.get(symbol)}


@router.put('/api/research/observation-cards/{symbol}')
def save_card(symbol: str, payload: dict[str, Any] = Body(...)):
    try:
        result = cards.save(symbol, payload.get('body'), payload.get('expected_version'))
        return {'card': result}
    except CardConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get('/api/research/us-references')
def references():
    return {'rows': cards.us_references()}
