from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.tasks import runner
from investment_assistant.workbench import ledger, service

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ledger.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ledger.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _date(value: Any, field: str) -> date | None:
    if value in (None, ''):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise HTTPException(status_code=400, detail=f'{field} must be YYYY-MM-DD') from None


@router.get('/api/workbench/today')
def today():
    return _call(service.today, now=_now())


@router.get('/api/workbench/instruments/{ticker}')
def instrument(ticker: str):
    return _call(service.instrument, ticker, now=_now())


@router.post('/api/workbench/decisions')
def decide(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.decide, payload, now=_now())


@router.get('/api/workbench/trades')
def list_trades():
    return {'trades': _call(service.list_trades)}


@router.post('/api/workbench/trades')
def add_trade(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.add_trade, payload, now=_now())


@router.post('/api/workbench/trades/{trade_id}/void')
def void_trade(trade_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.void_trade, trade_id, payload.get('reason'), now=_now())


@router.get('/api/workbench/account/snapshots')
def account_view():
    return _call(service.account_view)


@router.post('/api/workbench/account/snapshots')
def add_snapshot(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.add_snapshot, payload, now=_now())


@router.get('/api/workbench/account/flows')
def account_flows():
    return _call(service.account_view)


@router.post('/api/workbench/account/flows')
def add_flow(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.add_flow, payload, now=_now())


@router.post('/api/workbench/account/flows/{flow_id}/void')
def void_flow(flow_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.void_flow, flow_id, payload.get('reason'), now=_now())


@router.get('/api/workbench/plans/shadow')
def plans_shadow(since: str | None = None):
    return _call(service.plan_shadow, now=_now(), since=_date(since, 'since'))


@router.get('/api/workbench/review/shadow')
def shadow(since: str | None = None):
    return _call(service.shadow, now=_now(), since=_date(since, 'since'))


@router.get('/api/workbench/discipline')
def workbench_discipline():
    return _call(service.discipline, now=_now())


@router.get('/api/workbench/review/trades')
def trade_review():
    return _call(service.trade_review, now=_now())


@router.get('/api/workbench/weekly-reviews')
def weekly_reviews():
    return {'reviews': _call(service.list_weekly)}


@router.post('/api/workbench/weekly-reviews')
def generate_weekly(payload: dict[str, Any] = Body(default_factory=dict)):
    week_start = _date(payload.get('week_start'), 'week_start')
    if week_start is None:
        raise HTTPException(status_code=400, detail='week_start is required')
    return _call(service.generate_weekly, week_start, notes=payload.get('notes') or '',
                 supersedes_id=payload.get('supersedes_id') or None, now=_now())


@router.post('/api/workbench/run')
def run_now():
    from investment_assistant.tasks.workbench import run
    run_id = runner.submit('workbench', lambda: run(trigger_source='manual'))
    return {'run_id': run_id, 'status': 'pending'}
