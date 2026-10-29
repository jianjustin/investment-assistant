from datetime import UTC, date, datetime
from typing import Any

import psycopg.errors
from fastapi import APIRouter, Body, HTTPException

from investment_assistant.tasks import daily, runner
from investment_assistant.workbench import (derivation_view, discussion, ledger, my_knowledge, plan_review, reasoning,
                                            retro_cards, run_overview, service, user_inputs, workflow)
from investment_assistant.workbench.agent.chatgpt import ChatGPTError

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except daily.DailyBusy as exc:
        raise HTTPException(status_code=409, detail='daily_running') from exc
    except workflow.ResumeRejected as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc     # the code is the text: {"error": "<code>"}
    except (ledger.Conflict, service.AgentConflict, plan_review.RecheckConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatGPTError as exc:
        raise HTTPException(status_code=502, detail=exc.code) from exc     # only the safe code, never a response text
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
    try:
        busy = daily.is_running()
    except Exception:   # noqa: BLE001 - no database to ask: the run itself reports what is wrong
        busy = False
    if busy:
        raise HTTPException(status_code=409, detail='daily_running')
    _call(daily.ensure_ready)
    rid = daily.new_run_id()
    run_id = runner.submit('daily', lambda: daily.run(trigger_source='manual', run_id=rid))
    return {'run_id': run_id, 'status': 'pending', 'daily_run_id': rid}


@router.get('/api/workbench/agent-runs')
def agent_runs(since: str | None = None):
    return _call(service.agent_runs, now=_now(), since=_date(since, 'since'))


@router.get('/api/workbench/agent-runs/{run_id}')
def agent_run_detail(run_id: str):
    return _call(service.agent_run_detail, run_id)


@router.get('/api/workbench/agent-runs/{run_id}/reasoning')
def agent_run_reasoning(run_id: str):
    """v2.6 reading view of one agent run (spec §8): read-only; 400 not a UUID, 404 unknown run."""
    return _call(reasoning.reasoning, run_id)


@router.post('/api/workbench/agent-runs')
def run_agent(payload: dict[str, Any] = Body(default_factory=dict)):
    ticker = str(payload.get('ticker') or '')
    signal_date = _date(payload.get('signal_date'), 'signal_date')
    if not ticker or signal_date is None:
        raise HTTPException(status_code=400, detail='ticker 与 signal_date 必填')
    return _call(service.run_agent, ticker.upper(), signal_date, now=_now())


@router.post('/api/workbench/agent-runs/rerun')
def rerun_agent(payload: dict[str, Any] = Body(default_factory=dict)):
    """v2.8 D26 (spec §5.7): reset a unit's attempt gate and, for ``propose``, run it once now (synchronous, like the
    single-unit run above). 400 bad body / mode / origin, 404 no such unit, 409 ``not_needed``, 503 (migration 028 too).
    ``request_id`` makes a repeat harmless; ``origin`` defaults to ``api``."""
    ticker = str(payload.get('ticker') or '')
    signal_date = _date(payload.get('signal_date'), 'signal_date')
    if not ticker or signal_date is None:
        raise HTTPException(status_code=400, detail='ticker 与 signal_date 必填')
    try:
        return _call(service.rerun_agent, ticker.upper(), signal_date, str(payload.get('mode') or ''),
                     request_id=str(payload.get('request_id') or ''), origin=str(payload.get('origin') or 'api'),
                     now=_now())
    except psycopg.errors.UndefinedTable:      # the reset table belongs to migration 028
        raise HTTPException(status_code=503, detail='migration_028_missing') from None


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


@router.get('/api/workbench/run-overview')
def run_overview_view(session: str | None = None, run_id: str | None = None):
    """v2.6 run overview of one session (spec §7): read-only; 400 bad date, 404 run not of that day."""
    return _call(run_overview.overview, session=_date(session, 'session'), run_id=run_id or None, now=_now())


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


# --- v2.7 growth loop (spec §12): review cards, my knowledge, plan discussions ---
# The routes only parse parameters and map errors (400 ValueError, 404 LookupError, 409 Conflict, 503 Unavailable);
# transactions live in retro_cards / my_knowledge / discussion.

@router.get('/api/workbench/review-cards')
def review_cards(status: str | None = None, ticker: str | None = None, since: str | None = None):
    return _call(retro_cards.list_view, status=status or None, ticker=ticker.upper() if ticker else None,
                 since=_date(since, 'since'))


@router.get('/api/workbench/review-cards/{card_id}')
def review_card(card_id: int):
    return _call(retro_cards.card_view, card_id, now=_now())


@router.post('/api/workbench/review-cards/{card_id}/verdict')
def review_card_verdict(card_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(retro_cards.verdict, card_id, payload, now=_now())


@router.post('/api/workbench/review-cards/{card_id}/redraft')
def review_card_redraft(card_id: int):
    """Preconditions run here (503 / 404 / 409, nothing written); the draft runs in the background and the page
    polls ``/api/runs/<run_id>`` like a recheck."""
    now = _now()
    _call(retro_cards.redraft_check, card_id, now=now)
    run_id = runner.submit('retro_draft', lambda run_id: retro_cards.redraft(card_id, now=now, run_id=run_id),
                           with_run_id=True)
    return {'run_id': run_id, 'status': 'pending'}


@router.get('/api/workbench/my-knowledge')
def my_knowledge_list(ticker: str | None = None, concept: str | None = None, status: str = 'active'):
    return _call(my_knowledge.list_view, ticker=ticker or None, concept=concept or None, status=status)


@router.post('/api/workbench/my-knowledge')
def my_knowledge_create(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(my_knowledge.create, payload, now=_now())


@router.get('/api/workbench/my-knowledge/{knowledge_id}')
def my_knowledge_item(knowledge_id: int, version: int | None = None):
    return _call(my_knowledge.item_view, knowledge_id, version=version)


@router.post('/api/workbench/my-knowledge/{knowledge_id}/versions')
def my_knowledge_revise(knowledge_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(my_knowledge.revise, knowledge_id, payload, now=_now())


@router.post('/api/workbench/my-knowledge/{knowledge_id}/status')
def my_knowledge_status(knowledge_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(my_knowledge.set_status, knowledge_id, payload, now=_now())


@router.get('/api/workbench/my-knowledge/{knowledge_id}/performance')
def my_knowledge_performance(knowledge_id: int):
    return _call(my_knowledge.performance, knowledge_id, now=_now())


@router.get('/api/workbench/my-knowledge-drafts')
def my_knowledge_drafts(status: str = 'open'):
    if status not in ('open', 'all'):
        raise HTTPException(status_code=400, detail='status must be open or all')
    return _call(my_knowledge.drafts_view, open_only=status == 'open')


@router.post('/api/workbench/my-knowledge-drafts/{draft_id}/verdict')
def my_knowledge_draft_verdict(draft_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(my_knowledge.draft_verdict, draft_id, payload, now=_now())


@router.post('/api/workbench/discussions')
def discussion_create(payload: dict[str, Any] = Body(default_factory=dict)):
    return _call(discussion.create, payload, now=_now())


@router.get('/api/workbench/discussions')
def discussion_list(plan_id: str | None = None, card_id: int | None = None):
    if (plan_id is None) == (card_id is None):
        raise HTTPException(status_code=400, detail='plan_id 或 card_id 必须给一个')
    return {'discussions': _call(discussion.list_for, plan_id=plan_id, card_id=card_id)}


@router.get('/api/workbench/discussions/{discussion_id}')
def discussion_view(discussion_id: int):
    return _call(discussion.view, discussion_id)


@router.post('/api/workbench/discussions/{discussion_id}/turns', status_code=202)
def discussion_turn(discussion_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    """The checks and your turn are written here (503 / 404 / 409, 400 for a bad body); the answer is produced in
    the background and the page reads the discussion until it arrives (spec §8.2)."""
    now = _now()
    asked = _call(discussion.ask_check, discussion_id, payload, now=now)
    if asked['replayed']:
        return {'turn_id': asked['turn_id'], 'run_id': asked['run_id'], 'status': 'replayed'}
    try:
        run_id = runner.submit('discuss', lambda run_id: discussion.answer(discussion_id, asked['turn_id'], now=now,
                                                                          run_id=run_id), with_run_id=True)
    except Exception:
        discussion.release(asked['run_id'])
        raise
    discussion.track(asked['run_id'], run_id)
    return {'turn_id': asked['turn_id'], 'run_id': run_id, 'status': 'pending'}
