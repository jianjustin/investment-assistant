from typing import Any

from fastapi import APIRouter, Body

import investment_assistant.services.strategies as _strategies

router = APIRouter()


@router.get("/api/strategies/scores")
def scores():
    rows = _strategies.strategy_score_rows()
    return {"rows": rows, "count": len(rows)}


@router.post("/api/strategies/scores/run")
def run(payload: dict[str, Any] = Body(default_factory=dict)):
    return _strategies.run_strategy_score_scan(payload)
