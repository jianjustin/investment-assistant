from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.tasks import runner
from investment_assistant.workbench import derivation_view, ledger, plan_review, service, user_inputs

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ledger.Conflict, service.AgentConflict, plan_review.RecheckConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ledger.NotFound, LookupError) as exc:
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


@router.get('/api/workbench/screen')
def screen(session: str | None = None, full: int = 0):
    day = date.fromisoformat(session) if session else None
    return _call(service.screen_view, now=_now(), session=day, full=bool(full))


@router.post('/api/workbench/screen/replay')
def screen_replay(payload: dict[str, Any] = Body(default_factory=dict)):
    sessions = payload.get('sessions', 5)
    if not isinstance(sessions, int) or not 1 <= sessions <= 20:
        raise HTTPException(status_code=400, detail='sessions must be an integer in 1..20')
    return _call(service.replay_screen, now=_now(), sessions=sessions)


@router.get('/api/workbench/instruments/{ticker}')
def instrument(ticker: str):
    return _call(service.instrument, ticker, now=_now())


@router.get('/api/workbench/backchecks')
def backchecks(limit: int = 10):
    return {'backchecks': _call(service.list_backchecks, limit=limit)}


@router.post('/api/workbench/backchecks')
def run_backcheck(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(service.run_backcheck, now=_now(), tickers=payload.get('tickers'))


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


@router.get('/api/workbench/review/tracks')
def review_tracks(since: str | None = None, until: str | None = None):
    since_d = _date(since, 'since')
    until_d = _date(until, 'until')
    if since_d is not None and until_d is not None and since_d > until_d:
        raise HTTPException(status_code=400, detail='since must not be after until')
    return _call(service.tracks, now=_now(), since=since_d, until=until_d)


@router.get('/api/workbench/monthly-reviews')
def monthly_reviews():
    return {'reviews': _call(service.list_monthly)}


@router.post('/api/workbench/monthly-reviews')
def generate_monthly(payload: dict[str, Any] = Body(default_factory=dict)):
    month = _date(payload.get('month'), 'month')
    if month is None:
        raise HTTPException(status_code=400, detail='month is required')
    if month.day != 1:
        raise HTTPException(status_code=400, detail='month must be the first day of the month')
    return _call(service.generate_monthly, month, notes=payload.get('notes') or '',
                 supersedes_id=payload.get('supersedes_id') or None, now=_now())


@router.post('/api/workbench/push')
def push_today():
    from investment_assistant.config import load_config
    from investment_assistant.services.settings import effective_notify_config

    return _call(service.push, now=_now(), force=True,
                 notify_cfg=effective_notify_config(load_config().notify))


@router.post('/api/workbench/run')
def run_now():
    from investment_assistant.tasks.workbench import run
    run_id = runner.submit('workbench', lambda: run(trigger_source='manual'))
    return {'run_id': run_id, 'status': 'pending'}


@router.get('/api/workbench/agent-runs')
def agent_runs(since: str | None = None):
    return _call(service.agent_runs, now=_now(), since=_date(since, 'since'))


@router.get('/api/workbench/agent-runs/{run_id}')
def agent_run_detail(run_id: str):
    return _call(service.agent_run_detail, run_id)


@router.post('/api/workbench/agent-runs')
def run_agent(payload: dict[str, Any] = Body(default_factory=dict)):
    ticker = str(payload.get('ticker') or '')
    signal_date = _date(payload.get('signal_date'), 'signal_date')
    if not ticker or signal_date is None:
        raise HTTPException(status_code=400, detail='ticker 与 signal_date 必填')
    return _call(service.run_agent, ticker.upper(), signal_date, now=_now())


@router.get('/api/workbench/review-pushes')
def review_pushes(limit: int = 20):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail='limit must be between 1 and 100')
    return {'pushes': _call(service.list_review_pushes, limit=limit)}


@router.post('/api/workbench/review-pushes')
def review_push(payload: dict[str, Any] = Body(default_factory=dict)):
    kind = payload.get('kind')
    if kind not in ('weekly', 'monthly'):
        raise HTTPException(status_code=400, detail='kind must be weekly or monthly')
    period = _date(payload.get('period'), 'period')
    if period is None:
        raise HTTPException(status_code=400, detail='period is required')
    from investment_assistant.config import load_config
    from investment_assistant.services.settings import effective_notify_config
    return _call(service.push_review, kind, period, now=_now(),
                 notify_cfg=effective_notify_config(load_config().notify), trigger_source='manual')


@router.get('/api/workbench/plans/{plan_id}/derivation')
def plan_derivation_view(plan_id: str):
    result = _call(derivation_view.plan_derivation, plan_id)
    # 用例把触发段说明放在顶层 trigger_note；接口契约里它属于 trigger 段，不是顶层键
    result['trigger'] = {'note': result.pop('trigger_note'), 'candidates': result['trigger']}
    return result


@router.get('/api/workbench/units/{ticker}/{signal_date}/derivation')
def unit_derivation_view(ticker: str, signal_date: str):
    return _call(derivation_view.unit_derivation, ticker, _date(signal_date, 'signal_date'))


@router.get('/api/workbench/stage-runs')
def stage_runs(session: str | None = None, run_id: str | None = None):
    result = _call(derivation_view.stage_runs_view, session=_date(session, 'session'), run_id=run_id)
    result['stages'] = [{'id': s.id, 'title': s.title, 'purpose': s.purpose}   # StageDef 显式序列化
                        for s in result['stages']]
    return result


# --- v2.5 plan timeline (spec §8, §12): chains, reviews, recheck, user inputs ---

@router.get('/api/workbench/chains')
def ticker_chains(ticker: str | None = None):
    if not ticker:
        raise HTTPException(status_code=400, detail='ticker is required')
    return _call(plan_review.ticker_chains, ticker, now=_now())


@router.get('/api/workbench/chains/{ticker}/{signal_date}')
def chain_view(ticker: str, signal_date: str):
    return _call(plan_review.chain_view, ticker, _date(signal_date, 'signal_date'), now=_now())


@router.get('/api/workbench/plan-reviews')
def plan_reviews(session: str | None = None):
    day = _date(session, 'session')
    if day is None:
        raise HTTPException(status_code=400, detail='session is required')
    return _call(plan_review.reviews_view, day)


@router.post('/api/workbench/chains/{ticker}/{signal_date}/recheck')
def recheck_chain(ticker: str, signal_date: str):
    """Preconditions run here (503 / 404 / 409, nothing written); the review runs in the background with
    the cutoff taken now, when the request came in (D14)."""
    day = _date(signal_date, 'signal_date')
    now = _now()
    _call(plan_review.recheck_check, ticker, day, now=now)
    run_id = runner.submit('plan_recheck',
                           lambda run_id: plan_review.recheck(ticker, day, now=now, run_id=run_id),
                           with_run_id=True)
    return {'run_id': run_id, 'status': 'pending'}


@router.get('/api/workbench/user-inputs')
def list_user_inputs(ticker: str | None = None, signal_date: str | None = None):
    if not ticker:
        raise HTTPException(status_code=400, detail='ticker is required')
    return {'inputs': _call(user_inputs.list_for, ticker, _date(signal_date, 'signal_date'))}


@router.post('/api/workbench/user-inputs')
def add_user_input(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(user_inputs.add, payload, now=_now())
