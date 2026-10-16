from typing import Any

from fastapi import APIRouter, Body

from investment_assistant.us_research import service, guidance
from investment_assistant.tasks import runner

router = APIRouter()


@router.post('/api/us-research/sync')
def sync(payload: dict[str, Any] = Body(default_factory=dict)):
    from investment_assistant.tasks.us_research import run
    symbols, datasets = service.validate_request(payload.get('symbols'), payload.get('datasets'), payload.get('retry_failed', False))
    run_id = runner.submit('us-research', lambda: run(symbols=symbols, datasets=datasets,
                                                    retry_failed=payload.get('retry_failed', False)))
    return {'run_id': run_id, 'status': 'pending'}


@router.get('/api/us-research/{ticker}')
def view(ticker: str, as_of: str | None = None):
    return service.view(ticker, as_of=as_of)


@router.get('/api/us-research/{ticker}/guidance')
def guidance_history(ticker: str, as_of: str | None = None):
    return {'records': guidance.list_records(ticker, as_of=as_of), 'consensus': '未接入一致预期'}


@router.post('/api/us-research/{ticker}/guidance')
def add_guidance(ticker: str, payload: dict[str, Any] = Body(...)):
    return {'record': guidance.append(ticker, payload)}
