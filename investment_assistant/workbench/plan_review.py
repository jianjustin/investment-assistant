"""The daily review stage `review`, the per-chain review use case, the manual recheck, the chain read views
and the ``plan_review`` command line (v2.5 spec §7, §8.2, §12; `stages-2`).

After the agent stage, every active agent-2 chain (state ``entry`` or ``holding``, spec §5.3) is reviewed
once per trading day S: the host first (any met invalidation condition invalidates, D8; a quiet day with no
signal, no new user input and no met review condition maintains, D9), then — inside the budget gates — one
``agent-review-1`` call, and a revision (proposal + counter + checks, ``mode = 'revise'``) when the review
says ``revise``. Every outcome is one ``plan_reviews`` row.

Transactions: the chain's facts are read in one short transaction holding the chain's advisory lock; the
model runs with no transaction open; everything the review produces (review run, revise run, plan row,
version row, review row) is written in ONE transaction that takes the lock again and re-checks that the
head did not move (a recheck may have written a version meanwhile → ``review_in_progress``, no row).
A busy lock (a recheck running on the chain) skips the chain without a row.

On top of that, the whole review of one chain — read, model calls, write — runs under a session-level
advisory lock ``review-run:<ticker>:<signal_date>`` held on a connection of its own (``_run_lock``), so a
batch review, a recheck and a second recheck of the same chain never run their model calls side by side:
the later one skips (batch, no row) or is a 409 (recheck). The key differs from the transaction-level write
lock, so the review's own write transaction on another connection is not blocked by it.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable

from investment_assistant.data import identity
from investment_assistant.workbench import bars as bars_module
from investment_assistant.workbench import families, repository, service, timeline, user_inputs
from investment_assistant.workbench import plan_shadow as plan_shadow_module
from investment_assistant.workbench import stages as stages_module
from investment_assistant.workbench.agent import conditions as condition_registry
from investment_assistant.workbench.agent import graph as agent_graph
from investment_assistant.workbench.agent import model as agent_model
from investment_assistant.workbench.agent import tools as agent_tools

REVIEW_MAX_OBJECTS = 20
REVIEW_MAX_ATTEMPTS = 3
OUTCOMES = ('maintain', 'revise', 'invalidate', 'skipped', 'error')
ACTIVE_STATES = ('entry', 'holding')
ENDED_STATES = ('expired', 'closed_by_decision', 'position_closed')
DEFAULT_REVIEW_WHEN = [{'kind': 'next_session', 'params': {}}]
EMPTY_REASON = '（无理由）'


# ---------------------------------------------------------------- objects

def _chain_pool(conn, status: dict[str, Any]) -> str:
    """`pool` of the run that produced version 0 (main / extended)."""
    first = status['versions'][0] if status['versions'] else None
    run = repository.agent_run_by_id(conn, first['agent_run_id']) if first is not None else None
    return (run or {}).get('pool') or 'main'


def review_object(conn, ticker: str, signal_date: date, *, session: date, pool: str | None = None,
                  book: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One agent-2 chain read at S as a review object, or None without a chain. Keys: ticker,
    signal_date, state, mode, pool (version 0's), head ({'plan', 'version'}), version_no, as_of_session,
    valid_until. The caller decides whether the state is reviewable (``ACTIVE_STATES``)."""
    status = service.chain_status(conn, ticker, signal_date, session=session, book=book)
    if status is None:
        return None
    head = status['head']
    return {'ticker': head['version']['ticker'], 'signal_date': signal_date,
            'state': status['state']['state'], 'mode': status['state']['mode'],
            'pool': pool or _chain_pool(conn, status), 'head': head,
            'version_no': head['version']['version_no'], 'as_of_session': head['version']['as_of_session'],
            'valid_until': head['plan']['valid_until']}


def _order(obj: dict[str, Any]) -> tuple:
    """Holding first, then main-list entry, extended entry last (D6); each by valid_until, ticker."""
    rank = 0 if obj['mode'] == 'holding' else (2 if obj['pool'] == 'extended' else 1)
    return rank, obj['valid_until'], obj['ticker']


def review_objects(conn, session: date, *, now: datetime) -> tuple[list[dict], dict]:
    """(objects in review order, exclusions) for session S (spec §7.2).

    Objects are the chains in state entry / holding, minus a head generated on S (``fresh_version``) and a
    chain already holding an effective batch review for S (``already_reviewed``), capped at
    REVIEW_MAX_OBJECTS (``object_cap``, the tail of the order: extended entry chains go first). Exclusions:
    ``{'skips': [(reason, ticker)], 'excluded': [{ticker, signal_date, reason}] (the same exclusions per
    chain, uncapped), 'ended': {expired, closed_by_decision, position_closed}, 'failures': [(ticker, reason)],
    'holdings_without_chain': [ticker]}`` (held tickers without a chain in
    the holding state, D7). A chain whose reading raises is read under a savepoint and only listed in
    ``failures``; the other chains go on.
    Records are read as stored; ``now`` is the batch cutoff, kept for symmetry with the other readers."""
    objects: list[dict] = []
    skips: list[tuple[str, str]] = []
    excluded: list[dict] = []
    failures: list[tuple[str, str]] = []
    ended = {state: 0 for state in ENDED_STATES}
    holding: set[str] = set()
    for chain in repository.all_chains(conn):
        try:
            with conn.transaction():        # savepoint: a broken chain must not abort the others' reads
                obj = review_object(conn, chain['ticker'], chain['signal_date'], session=session,
                                    pool=chain['pool'])
                reviewed = obj is not None and any(
                    r['outcome'] in repository.EFFECTIVE_REVIEW_OUTCOMES
                    for r in repository.batch_attempts(conn, obj['ticker'], obj['signal_date'], session))
        except service.Unavailable:
            raise
        except Exception as exc:            # §7.4 / §13: one chain's surprise only affects that chain
            failures.append((chain['ticker'], families.sanitize_reason(exc)))
            continue
        if obj is None:
            continue
        if obj['state'] in ended:
            ended[obj['state']] += 1
            continue
        if obj['state'] not in ACTIVE_STATES:
            continue
        if obj['state'] == 'holding':
            holding.add(obj['ticker'])
        reason = ('fresh_version' if obj['as_of_session'] == session
                  else 'already_reviewed' if reviewed else None)
        if reason is not None:
            skips.append((reason, obj['ticker']))
            excluded.append(_excluded(obj, reason))
            continue
        objects.append(obj)
    objects.sort(key=_order)
    skips += [('object_cap', obj['ticker']) for obj in objects[REVIEW_MAX_OBJECTS:]]
    excluded += [_excluded(obj, 'object_cap') for obj in objects[REVIEW_MAX_OBJECTS:]]
    held = repository.open_position_tickers(conn)
    return objects[:REVIEW_MAX_OBJECTS], {'skips': skips, 'excluded': excluded, 'ended': ended,
                                          'failures': failures, 'holdings_without_chain': sorted(held - holding)}


def _excluded(obj: dict, reason: str) -> dict:
    """One chain the stage did not review on S, as recorded in the stage's ``detail.excluded``."""
    return {'ticker': obj['ticker'], 'signal_date': obj['signal_date'].isoformat(), 'reason': reason}


def chain_tickers(conn, session: date, *, now: datetime, exclude: Iterable[str],
                  failures: list[tuple[str, str]] | None = None) -> list[str]:
    """Tickers of chains in state entry / holding at S that are not in ``exclude`` (the batch passes its
    pool and holdings): collected only, never run through the rules (D21). A chain whose state cannot be
    read (under a savepoint) is appended to ``failures`` as (ticker, reason) and skipped."""
    skip = {t.upper() for t in exclude}
    out: set[str] = set()
    for chain in repository.all_chains(conn):
        if chain['ticker'].upper() in skip or chain['ticker'] in out:
            continue
        try:
            with conn.transaction():
                status = service.chain_status(conn, chain['ticker'], chain['signal_date'], session=session)
        except service.Unavailable:
            raise
        except Exception as exc:
            if failures is not None:
                failures.append((chain['ticker'], families.sanitize_reason(exc)))
            continue
        if status is not None and status['state']['state'] in ACTIVE_STATES:
            out.add(chain['ticker'])
    return sorted(out)


# ---------------------------------------------------------------- facts (read phase)

def _dec_bars(rows: list[dict]) -> list[dict]:
    return [{**b, **{k: Decimal(str(b[k])) for k in ('open', 'high', 'low', 'close')}} for b in rows]


def _filing_in(filing: dict, *, after_session: date, after_at: datetime, session: date, now: datetime) -> bool:
    """Accepted in (after_at, now]; without an acceptance time, filed in (after_session, session]."""
    accepted = filing.get('accepted_at')
    if accepted is not None:
        return after_at < accepted <= now
    return after_session < filing['filing_date'] <= session


def _read(conn, ticker: str, signal_date: date, *, session: date, now: datetime, trigger: str,
          filings_known: bool) -> dict[str, Any]:
    """Everything the host needs, read at cutoff ``now``; ``{'skip': reason}`` when the chain is not
    reviewable right now (not active, fresh head, already reviewed by the batch on S)."""
    status = service.chain_status(conn, ticker, signal_date, session=session)
    if status is None or status['state']['state'] not in ACTIVE_STATES:
        return {'skip': 'chain_not_active'}
    head = status['head']
    version, plan = head['version'], head['plan']
    if trigger == 'batch' and version['as_of_session'] == session:
        return {'skip': 'fresh_version'}
    attempts = (repository.batch_attempts(conn, ticker, signal_date, session) if trigger == 'batch'
                else [r for r in status['reviews'] if r['session'] == session and r['trigger'] == trigger])
    if trigger == 'batch' and any(r['outcome'] in repository.EFFECTIVE_REVIEW_OUTCOMES for r in attempts):
        return {'skip': 'already_reviewed'}
    last = repository.last_effective_review(conn, plan['id'])
    since_session, since_at = timeline.since_window(version, last)
    regime_row = repository.regime_for(conn, session, cutoff_at=now)
    context = (plan.get('inputs') or {}).get('context') or {}
    entry = repository.pool_entry_at(conn, ticker, session, cutoff_at=now)
    etf = (entry or {}).get('sector_etf') or (context.get('sector') or {}).get('etf')
    sector = ((regime_row or {}).get('sectors') or {}).get(etf) if etf else None
    earnings = repository.latest_earnings(conn, ticker, cutoff_at=now)
    events, _ = service._filing_events(conn, ticker, session, now, since=version['as_of_session'])
    inputs = timeline.effective_inputs(repository.user_inputs_for(conn, ticker, signal_date), now)
    return {
        'status': status, 'head': head, 'version': version, 'plan': plan, 'mode': status['state']['mode'],
        'pool': _chain_pool(conn, status),
        'run': repository.agent_run_by_id(conn, version['agent_run_id']), 'last_review': last,
        'attempts': attempts, 'since_session': since_session, 'since_at': since_at,
        'bars': repository.read_bars(conn, ticker, session, cutoff_at=now),
        'spy': repository.read_bars(conn, service.BENCHMARK, session, cutoff_at=now),
        'filings': sorted(events, key=lambda f: (f['filing_date'], str(f['id']))) if filings_known else None,
        'abnormal': [c for c in repository.read_candidates(conn, ticker, since=since_session)
                     if c['rule_id'] == 'abnormal_move'],
        'regime_label': regime_row['label'] if regime_row is not None else None,
        'sector_state': (sector or {}).get('state'),
        'earnings_date': (earnings['earnings_date'] if earnings and earnings['status'] == 'known' else None),
        'inputs_new': [r for r in inputs if r['created_at'] > since_at],
        'inputs_old': [r for r in inputs if r['created_at'] <= since_at],
        'trigger_rows': repository.unit_candidates(conn, ticker, signal_date),
    }


def _assess(seen: dict[str, Any], *, session: date, now: datetime) -> tuple[list, list]:
    """(signals, conditions) of spec §7.3 from the read facts."""
    version, plan, mode = seen['version'], seen['plan'], seen['mode']
    as_of, since_session, since_at = version['as_of_session'], seen['since_session'], seen['since_at']
    bars = _dec_bars(seen['bars'])
    after_version = [b for b in bars if as_of < b['price_date'] <= session]
    since_review = [b for b in bars if since_session < b['price_date'] <= session]
    indicators = agent_tools.indicators(seen['bars'], seen['spy'])
    filings = seen['filings']

    def window(after_session: date, after_at: datetime) -> list[dict] | None:
        if filings is None:
            return None
        return [f for f in filings if _filing_in(f, after_session=after_session, after_at=after_at,
                                                 session=session, now=now)]

    common = dict(session=session, mode=mode, bars_since_version=after_version,
                  entry_low=Decimal(str(plan['entry_low'])), entry_high=Decimal(str(plan['entry_high'])),
                  regime_label=seen['regime_label'], sector_state=seen['sector_state'],
                  earnings_date=seen['earnings_date'], rs={20: indicators['rs20'], 60: indicators['rs60']},
                  as_of_session=as_of)
    output = (seen['run'] or {}).get('output') or {}
    conditions = timeline.condition_results(
        invalidation=output.get('invalidation') or [],
        review_when=output.get('review_when') or DEFAULT_REVIEW_WHEN,
        invalidation_facts=condition_registry.Facts(bars=after_version,
                                                    filings=window(as_of, version['cutoff_at']), **common),
        review_facts=condition_registry.Facts(bars=since_review, filings=window(since_session, since_at),
                                               **common))
    signals = timeline.signals(head_plan=plan, mode=mode, session=session, since_session=since_session,
                               since_at=since_at, now=now, bars=seen['bars'], filings=filings,
                               abnormal=seen['abnormal'], regime_label=seen['regime_label'],
                               new_inputs=seen['inputs_new'])
    return signals, conditions


# ---------------------------------------------------------------- model calls

def _invoke(call: Callable[[Any, Any], dict], *, deps, settings) -> tuple[dict | None, tuple[str, str] | None]:
    """(result, None) or (None, (reason, detail)): checkpointer, model and error classification exactly
    as service._run_agent_unit does them."""
    with ExitStack() as stack:
        try:
            factory = deps.agent_checkpointer or (
                lambda: agent_model.checkpointer(os.environ.get('INVESTMENT_ASSISTANT_DATABASE_URL', '')))
            checkpointer = stack.enter_context(factory())
        except Exception as exc:
            _, detail = agent_model.classify_error(exc, settings.api_key)
            return None, ('checkpoint_unavailable', detail)
        try:
            model = deps.agent_model if deps.agent_model is not None else agent_model.chat_model(settings)
            return call(model, checkpointer), None
        except service.Unavailable:
            raise
        except Exception as exc:
            reason, detail = agent_model.classify_error(exc, settings.api_key)
            if service._checkpoint_missing(exc):
                reason = 'checkpoint_unavailable'
            return None, (reason, detail)


def _reason(text: Any, settings) -> str:
    """A review reason as stored: model key and FRED key redacted, at most 300 characters, never blank."""
    cleaned = families.sanitize_reason(agent_model.redact(str(text or ''), settings.api_key)).strip()
    return cleaned or EMPTY_REASON


# ---------------------------------------------------------------- one chain

def _lock_connection():
    """A connection of its own for the run lock: a session-level lock must not ride on a connection whose
    transactions commit and roll back underneath it."""
    return service.connection()


@contextmanager
def _run_lock(ticker: str, signal_date: date):
    """Try the chain's session-level run lock ``review-run:<ticker>:<signal_date>``; yields whether it is
    held. Held for the whole ``with`` block on a dedicated connection and released on the way out. The
    connection comes from the process pool and goes back to it, so if the unlock itself fails the
    connection is closed (a closed connection releases its session locks and the pool drops it) rather than
    returned still holding the lock."""
    import psycopg

    key = f'review-run:{ticker.upper()}:{signal_date.isoformat()}'
    try:
        with _lock_connection() as conn:
            got = bool(conn.execute('SELECT pg_try_advisory_lock(hashtext(%s))', (key,)).fetchone()[0])
            conn.commit()
            try:
                yield got
            finally:
                if got:
                    try:
                        if conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
                            conn.rollback()
                        conn.execute('SELECT pg_advisory_unlock(hashtext(%s))', (key,))
                        conn.commit()
                    except Exception:      # noqa: BLE001 - never hand a pooled connection back still locked
                        conn.close()
    except psycopg.OperationalError:
        raise service.Unavailable('数据库不可达') from None


def review_chain(obj: dict, *, session: date, now: datetime, trigger: str, run_id: str | None, deps, settings,
                 started: float, clock: Callable[[], float], quota: dict) -> dict:
    """Review one chain under its run lock (a busy lock → ``{'skipped_without_row': 'review_in_progress'}``,
    nothing read, no model call); see ``_review_chain`` for the review itself."""
    with _run_lock(obj['ticker'], obj['signal_date']) as got:
        if not got:
            return {'skipped_without_row': 'review_in_progress'}
        return _review_chain(obj, session=session, now=now, trigger=trigger, run_id=run_id, deps=deps,
                             settings=settings, started=started, clock=clock, quota=quota)


def _review_chain(obj: dict, *, session: date, now: datetime, trigger: str, run_id: str | None, deps, settings,
                  started: float, clock: Callable[[], float], quota: dict) -> dict:
    """Review one chain at session S and cutoff ``now`` (spec §7.3–§7.4); returns the written plan_reviews
    row, or ``{'skipped_without_row': reason}`` (review_in_progress, fresh_version, already_reviewed,
    max_attempts, chain_not_active).

    ``obj`` needs ticker and signal_date (pool and filings_known optional: the SEC listing of this batch
    failed → filings unknown). ``trigger`` is 'batch' or 'recheck' (a recheck skips the quiet-day maintain,
    is not limited by REVIEW_MAX_ATTEMPTS and writes origin 'recheck' versions). ``quota`` is the run's
    shared ``{'exhausted': bool}``, set here when a call hits the quota. Model and checkpoint failures
    become an ``error`` row; so does a failure inside the write transaction (it is rolled back, then an
    ``error`` row with ``detail.write_error`` and the model runs as ``error`` rows, tokens kept, is written in
    a new one, so attempts and the token cap still count). Failures before any write propagate (the stage
    isolates them per chain)."""
    ticker, signal_date = obj['ticker'], obj['signal_date']
    recheck = trigger == 'recheck'
    with service._tx() as conn:
        if not repository.try_review_lock(conn, ticker, signal_date):
            return {'skipped_without_row': 'review_in_progress'}
        seen = _read(conn, ticker, signal_date, session=session, now=now, trigger=trigger,
                     filings_known=obj.get('filings_known', True))
    if 'skip' in seen:
        return {'skipped_without_row': seen['skip']}
    pool = obj.get('pool') or seen['pool']
    signals, conditions = _assess(seen, session=session, now=now)
    included, omitted = timeline.select_new_inputs(seen['inputs_new'])
    detail: dict[str, Any] = {}
    if not any(b['price_date'] == session for b in seen['bars']):
        detail['bars_missing'] = True                 # §13: signals / conditions stay unknown or quiet
    if omitted:
        detail['inputs_omitted'] = omitted
    base = {'ticker': ticker, 'signal_date': signal_date, 'head_plan_id': seen['plan']['id'], 'session': session,
            'trigger': trigger, 'run_id': run_id, 'mode': seen['mode'], 'timeline_version': timeline.TIMELINE_VERSION,
            'signals': signals, 'conditions': conditions, 'user_input_ids': [r['id'] for r in included],
            'cutoff_at': now, 'detail': detail}
    unit = {'ticker': ticker, 'signal_date': signal_date, 'pool': pool}
    spent: dict[str, tuple[str, int, int]] = {}      # model runs made so far: run id -> (mode, in, out)

    def run_row(run_id_: str, mode: str, status: str, attempt: int, **kwargs) -> dict:
        return service._agent_run_row(unit, settings=settings, attempt=attempt, now=now, status=status,
                                      run_id=run_id_, mode=mode, **kwargs)

    def commit(build: Callable[[Any, int], dict]) -> dict:
        try:
            out = _commit(seen, ticker=ticker, signal_date=signal_date, session=session, trigger=trigger,
                          build=build)
        except service.Unavailable:
            raise
        except Exception as exc:      # the write failed and rolled back: record it, so attempts and tokens count
            out = _commit(seen, ticker=ticker, signal_date=signal_date, session=session, trigger=trigger,
                          build=lambda conn, attempt: _write_failed(conn, attempt, exc=exc, base=base,
                                                                    spent=spent, run_row=run_row,
                                                                    settings=settings))
        if 'skipped_without_row' in out and spent:
            _record_lost_runs(spent, reason=out['skipped_without_row'], run_row=run_row,
                              attempt=len(seen['attempts']) + 1)
        return out

    verdict = timeline.host_verdict(signals=signals, conditions=conditions, recheck=recheck)
    if verdict is not None:                           # §7.4 steps 1–2: the host decides, no model call
        return commit(lambda conn, attempt: {**base, 'outcome': verdict['outcome'], 'decided_by': 'host',
                                             'reason': _reason(verdict['reason'], settings), 'attempt': attempt})

    if not recheck and len(seen['attempts']) >= REVIEW_MAX_ATTEMPTS:
        return {'skipped_without_row': 'max_attempts'}
    gate = _gate(settings, started=started, clock=clock, quota=quota, now=now)
    if gate is not None:                              # §7.4 step 3
        return commit(lambda conn, attempt: {**base, 'outcome': 'skipped', 'decided_by': 'host',
                                             'reason': gate, 'attempt': attempt})

    output = (seen['run'] or {}).get('output') or {}
    evidence = timeline.prompt_evidence(
        head={'version': seen['version'], 'plan': seen['plan'], 'output': output,
              'counter': (seen['run'] or {}).get('counter')},
        trigger=seen['trigger_rows'], signals=signals, conditions=conditions, inputs_new=seen['inputs_new'],
        inputs_old=seen['inputs_old'], last_review=seen['last_review'])
    user_refs = frozenset(f"user:{r['id']}" for r in [*included, *seen['inputs_old']])
    context = (seen['plan'].get('inputs') or {}).get('context') or {}
    graph_unit = {'ticker': ticker, 'signal_date': signal_date, 'pool_tier': context.get('pool_tier')}
    ctx = agent_tools.ToolContext(ticker=ticker, session=session, cutoff_at=now, read=service._read_only)

    review_id = str(uuid.uuid4())                     # §7.4 step 4: agent-review-1, single phase
    reviewed, failure = _invoke(
        lambda model, checkpointer: agent_graph.run_review(
            unit=graph_unit, ctx=ctx, model=model, checkpointer=checkpointer, run_id=review_id,
            now=lambda: now, evidence=evidence, user_refs=user_refs), deps=deps, settings=settings)
    spent[review_id] = ('review', 0, 0) if failure is not None else (
        'review', reviewed['input_tokens'] or 0, reviewed['output_tokens'] or 0)
    if failure is not None:
        reason, error_detail = failure
        if reason == 'quota_exhausted':
            quota['exhausted'] = True

        def failed(conn, attempt: int) -> dict:
            repository.insert_agent_run(conn, run_row(review_id, 'review', 'error', attempt, reason=reason,
                                                      detail=error_detail), [])
            return {**base, 'outcome': 'error', 'decided_by': 'agent', 'reason': reason,
                    'review_agent_run_id': review_id, 'attempt': attempt}
        return commit(failed)

    review_tokens = (reviewed['input_tokens'] or 0, reviewed['output_tokens'] or 0)

    def review_run(conn, attempt: int) -> None:
        repository.insert_agent_run(conn, run_row(review_id, 'review', reviewed['status'], attempt,
                                                  reason=reviewed['reason'], output=reviewed['output'],
                                                  input_tokens=review_tokens[0], output_tokens=review_tokens[1]),
                                    reviewed['calls'])

    review_base = {**base, 'review_agent_run_id': review_id, 'input_tokens': review_tokens[0],
                   'output_tokens': review_tokens[1]}
    if reviewed['status'] != 'ok':                    # review_malformed / invalid_citation / tool_rounds_exceeded
        def rejected(conn, attempt: int) -> dict:
            review_run(conn, attempt)
            return {**review_base, 'outcome': 'error', 'decided_by': 'agent', 'reason': reviewed['reason'],
                    'attempt': attempt}
        return commit(rejected)

    said = reviewed['output']
    said_base = {**review_base, 'decided_by': 'agent', 'reason': _reason(said['reason'], settings),
                 'refs': said.get('refs') or []}
    if said['outcome'] in ('maintain', 'invalidate'):  # §7.4 step 5
        def concluded(conn, attempt: int) -> dict:
            review_run(conn, attempt)
            return {**said_base, 'outcome': said['outcome'], 'attempt': attempt}
        return commit(concluded)

    # §7.4 step 6: revise — the full proposal + counter + checks, mode 'revise', at most once
    revise_id = str(uuid.uuid4())
    bars = seen['bars']
    if bars:
        revised, failure = _invoke(
            lambda model, checkpointer: agent_graph.run_unit_v2(
                unit=graph_unit, ctx=ctx, model=model, checkpointer=checkpointer, run_id=revise_id,
                last_close=Decimal(str(bars[-1]['close'])), as_of_session=session, now=lambda: now,
                previous=output, evidence=evidence, user_refs=user_refs, review_reason=said['reason']),
            deps=deps, settings=settings)
    else:
        revised, failure = None, ('bars_missing', 'no bars through the review session')
    if failure is not None and failure[0] == 'quota_exhausted':
        quota['exhausted'] = True
    spent[revise_id] = ('revise', 0, 0) if revised is None else (
        'revise', revised['input_tokens'] or 0, revised['output_tokens'] or 0)
    return commit(lambda conn, attempt: _revision(
        conn, attempt, seen=seen, said_base=said_base, review_run=review_run, run_row=run_row,
        revise_id=revise_id, revised=revised, failure=failure, session=session, now=now, trigger=trigger,
        settings=settings))


def _gate(settings, *, started: float, clock: Callable[[], float], quota: dict, now: datetime) -> str | None:
    """§7.4 step 3, in the agent stage's order: stage budget, provider, quota, daily tokens."""
    unavailable = agent_model.unavailable_reason(settings)
    if clock() - started >= service.AGENT_DEADLINE_S:
        return 'stage_budget'
    if unavailable is not None:
        return unavailable
    if quota.get('exhausted'):
        return 'quota_exhausted'
    if settings.daily_tokens is not None:
        with service._tx() as conn:
            used = repository.agent_tokens_on(conn, now.astimezone(service.NY).date())
        if used >= settings.daily_tokens:
            return 'token_budget'
    return None


def _revision(conn, attempt: int, *, seen: dict, said_base: dict, review_run: Callable, run_row: Callable,
              revise_id: str, revised: dict | None, failure: tuple[str, str] | None, session: date,
              now: datetime, trigger: str, settings) -> dict:
    """Inside the write transaction: the revise run, and on success the new plan + version (spec §5.2);
    returns the review row. Failed revision (D10, D23) → outcome revise without new_plan_id; pass → the
    review becomes an invalidation (D11)."""
    from investment_assistant.config import load_config

    review_run(conn, attempt)
    row = {**said_base, 'outcome': 'revise', 'revision_agent_run_id': revise_id, 'attempt': attempt}
    if failure is not None:
        reason, error_detail = failure
        repository.insert_agent_run(conn, run_row(revise_id, 'revise', 'error', attempt, reason=reason,
                                                  detail=error_detail), [])
        return {**row, 'detail': {**row['detail'], 'revision_status': f'error: {reason}'}}
    tokens = {'input_tokens': revised['input_tokens'] or 0, 'output_tokens': revised['output_tokens'] or 0}
    row['input_tokens'] += tokens['input_tokens']
    row['output_tokens'] += tokens['output_tokens']
    payload = {'output': revised['output'], 'counter': revised['counter'], **tokens}
    if revised['status'] == 'pass':
        repository.insert_agent_run(conn, run_row(revise_id, 'revise', 'pass', attempt, **payload),
                                    revised['calls'])
        summary = (revised['output'] or {}).get('summary')
        return {**row, 'outcome': 'invalidate', 'reason': _reason(summary or row['reason'], settings),
                'detail': {**row['detail'], 'via': 'revision_pass'}}
    if revised['status'] != 'ok':
        repository.insert_agent_run(conn, run_row(revise_id, 'revise', revised['status'], attempt,
                                                  reason=revised['reason'], **payload), revised['calls'])
        return {**row, 'detail': {**row['detail'],
                                  'revision_status': f"{revised['status']}: {revised['reason']}"}}

    ticker, signal_date, mode = seen['version']['ticker'], seen['version']['signal_date'], seen['mode']
    head_plan, head_version = seen['plan'], seen['version']
    plan = timeline.build_version_plan(
        output=revised['output'], agent_run_id=revise_id, model=settings.model, ticker=ticker,
        signal_date=signal_date, as_of_session=session, version_no=head_version['version_no'] + 1,
        supersedes_plan_id=str(head_plan['id']), mode=mode, bars=seen['bars'],
        earnings_row=repository.latest_earnings(conn, ticker, cutoff_at=now),
        snapshot=repository.snapshot_at(conn, session, cutoff_at=now),
        exposure=service.exposure(conn, session, cutoff_at=now, ticker=ticker),
        params=load_config().workbench, context=service.plan_context(conn, ticker, session, now=now))
    if mode == 'entry' and plan['status'] == 'invalid':      # D23: an entry revision must be adoptable
        reasons = ', '.join(plan['invalid_reasons'])
        repository.insert_agent_run(conn, run_row(revise_id, 'revise', 'rejected', attempt, reason='plan_invalid',
                                                  detail=reasons, **payload), revised['calls'])
        return {**row, 'detail': {**row['detail'], 'revision_status': f'plan_invalid: {reasons}'}}
    plan_id = repository.store_plan(conn, plan)['record']['id']
    repository.insert_agent_run(conn, run_row(revise_id, 'revise', 'ok', attempt, plan_id=plan_id, **payload),
                                revised['calls'])
    repository.insert_plan_version(conn, {
        'plan_id': plan_id, 'ticker': ticker, 'signal_date': signal_date,
        'version_no': head_version['version_no'] + 1, 'supersedes_plan_id': head_plan['id'],
        'origin': 'recheck' if trigger == 'recheck' else 'review', 'agent_run_id': revise_id, 'cutoff_at': now,
        'as_of_session': session, 'diff': (revised['output'] or {}).get('diff') or [],
        'schema_version': timeline.AGENT_V2})
    return {**row, 'new_plan_id': plan_id}


def _record_lost_runs(spent: dict, *, reason: str, run_row: Callable, attempt: int) -> None:
    """The chain moved while the model ran (a decision, or a review written without the run lock), so the
    review writes no row; its model runs are still recorded — ``skipped`` with the reason and their tokens —
    so the daily token cap counts them."""
    with service._tx() as conn:
        for run_id, (mode, tokens_in, tokens_out) in spent.items():
            repository.insert_agent_run(conn, run_row(run_id, mode, 'skipped', attempt, reason=reason,
                                                      input_tokens=tokens_in, output_tokens=tokens_out), [])


def _write_failed(conn, attempt: int, *, exc: BaseException, base: dict, spent: dict, run_row: Callable,
                  settings) -> dict:
    """The review row after a failed write: every model run made so far as an ``error`` run with its
    tokens, outcome ``error`` with the classified reason and ``detail.write_error``."""
    reason, error_detail = agent_model.classify_error(exc, settings.api_key)
    ids = {'review': None, 'revise': None}
    for run_id, (mode, tokens_in, tokens_out) in spent.items():
        repository.insert_agent_run(conn, run_row(run_id, mode, 'error', attempt, reason=reason, detail=error_detail,
                                                  input_tokens=tokens_in, output_tokens=tokens_out), [])
        ids[mode] = run_id
    return {**base, 'outcome': 'error', 'decided_by': 'agent' if ids['review'] else 'host', 'reason': reason,
            'review_agent_run_id': ids['review'], 'revision_agent_run_id': ids['revise'],
            'input_tokens': sum(v[1] for v in spent.values()), 'output_tokens': sum(v[2] for v in spent.values()),
            'attempt': attempt, 'detail': {**base['detail'], 'write_error': error_detail}}


def _commit(seen: dict, *, ticker: str, signal_date: date, session: date, trigger: str,
            build: Callable[[Any, int], dict]) -> dict:
    """The one write transaction of a review: lock, then re-check what the read saw — the chain is still
    active in the same mode, the head is the same version and no effective review of it was written since
    (a recheck or a decision may have landed while the model ran; otherwise ``review_in_progress``, no row) —
    and (batch) not yet reviewed on S; then ``build(conn, attempt)`` inserts its runs / plan / version and
    returns the review row, inserted last."""
    with service._tx() as conn:
        if not repository.try_review_lock(conn, ticker, signal_date):
            return {'skipped_without_row': 'review_in_progress'}
        status = service.chain_status(conn, ticker, signal_date, session=session)
        if (status is None or status['state']['state'] not in ACTIVE_STATES
                or status['state']['mode'] != seen['mode']
                or str(status['head']['plan']['id']) != str(seen['plan']['id'])):
            return {'skipped_without_row': 'review_in_progress'}       # someone else moved the chain meanwhile
        if trigger == 'batch':
            attempts = repository.batch_attempts(conn, ticker, signal_date, session)
            if any(r['outcome'] in repository.EFFECTIVE_REVIEW_OUTCOMES for r in attempts):
                return {'skipped_without_row': 'already_reviewed'}
        else:
            attempts = [r for r in status['reviews'] if r['session'] == session and r['trigger'] == trigger]
        last = repository.last_effective_review(conn, seen['plan']['id'])
        if (last or {}).get('id') != (seen['last_review'] or {}).get('id'):
            return {'skipped_without_row': 'review_in_progress'}       # the head was reviewed meanwhile
        return repository.insert_plan_review(conn, build(conn, len(attempts) + 1))


# ---------------------------------------------------------------- the stage

def _empty_review() -> dict[str, Any]:
    return {'objects': 0, 'outcomes': {outcome: 0 for outcome in OUTCOMES}, 'tokens': {'input': 0, 'output': 0}}


def run_stage(session: date, *, now: datetime, deps, summary: dict[str, Any], started: float,
              clock: Callable[[], float], run_id: str | None, acc: stages_module.StageAcc | None,
              timeline_ready: bool | None = None) -> str | None:
    """The batch's review stage (spec §7.1): ``summary['review'] = {objects, outcomes, tokens}`` and, with
    ``acc``, the stage accounting including the derivation check of this run's new versions.

    Returns a whole-stage skip reason for the caller to record — ``migration_026_missing`` (the agent
    stage already reported it in ``summary['errors']``) or ``agent_unavailable: <reason>`` when the agent
    is unavailable and there is nothing to review — else None (finish the stage)."""
    t_stage = clock()
    review = summary['review'] = _empty_review()
    settings = deps.agent_settings if deps.agent_settings is not None else agent_model.settings_from_env()
    with service._tx() as conn:
        ready = repository.timeline_ready(conn) if timeline_ready is None else timeline_ready
        objects, excluded = review_objects(conn, session, now=now) if ready else ([], None)
    if not ready:
        return 'migration_026_missing'
    summary['errors'].extend(f'{ticker} review: {reason}' for ticker, reason in excluded['failures'])
    unavailable = agent_model.unavailable_reason(settings)
    review['objects'] = len(objects)
    detail = {'outcomes': dict(review['outcomes']), 'decided_by': {'agent': 0, 'host': 0},
              'signals': {kind: 0 for kind in timeline.SIGNAL_KINDS},
              'modes': {'entry': 0, 'holding': 0}, 'ended': excluded['ended'],
              'excluded': list(excluded['excluded']),
              'holdings_without_chain': excluded['holdings_without_chain'], 'tokens': review['tokens']}
    if acc is not None:
        acc.input(len(objects))
        for reason, ticker in excluded['skips']:
            acc.skip(reason, ticker)
        for ticker, reason in excluded['failures']:
            acc.fail(ticker, reason)
        acc.outputs.update({'review_ids': [], 'plan_ids': [], 'agent_run_ids': []})
        acc.detail.update(detail)
        if unavailable is not None and objects:
            acc.degrade('agent_unavailable', unavailable)
    for obj in objects:
        detail['modes'][obj['mode']] += 1
    if unavailable is not None and not objects:
        if acc is not None:
            acc.duration_ms += (clock() - t_stage) * 1000
        return f'agent_unavailable: {unavailable}'

    quota = {'exhausted': bool((summary.get('agent') or {}).get('quota_exhausted'))}
    sec_known = not (isinstance(summary.get('filings'), dict) and 'error' in summary['filings'])
    for obj in objects:
        try:
            out = review_chain({**obj, 'filings_known': sec_known}, session=session, now=now, trigger='batch',
                               run_id=run_id, deps=deps, settings=settings, started=started, clock=clock,
                               quota=quota)
        except service.Unavailable:
            raise
        except Exception as exc:    # §13: one chain's surprise never stops the stage
            summary['errors'].append(f"{obj['ticker']} review: {families.sanitize_reason(exc)}")
            if acc is not None:
                acc.fail(obj['ticker'], exc)
            continue
        _record(obj, out, review=review, detail=detail, acc=acc)
        if (out.get('detail') or {}).get('write_error'):
            summary['errors'].append(f"{obj['ticker']} review: {out['detail']['write_error']}")

    detail['outcomes'] = dict(review['outcomes'])
    if acc is not None:
        acc.detail.update(detail)
        service._check_derivations(acc, acc.outputs['plan_ids'], summary)
        acc.duration_ms += (clock() - t_stage) * 1000
    return None


def _record(obj: dict, out: dict, *, review: dict, detail: dict, acc: stages_module.StageAcc | None) -> None:
    """Fold one chain's result into summary['review'] and the stage accumulator."""
    ticker = obj['ticker']
    if 'skipped_without_row' in out:
        detail['excluded'].append(_excluded(obj, out['skipped_without_row']))
        if acc is not None:
            acc.skip(out['skipped_without_row'], ticker)
        return
    outcome = out['outcome']
    review['outcomes'][outcome] += 1
    review['tokens']['input'] += out['input_tokens'] or 0
    review['tokens']['output'] += out['output_tokens'] or 0
    detail['decided_by'][out['decided_by']] += 1
    for item in out['signals'] or []:
        if item.get('fired') and item.get('kind') in detail['signals']:
            detail['signals'][item['kind']] += 1
    if acc is None:
        return
    acc.ref('review_ids', out['id'])
    for run in (out['review_agent_run_id'], out['revision_agent_run_id']):
        if run is not None:
            acc.ref('agent_run_ids', str(run))
    if out['new_plan_id'] is not None:
        acc.ref('plan_ids', str(out['new_plan_id']))
    if outcome in repository.EFFECTIVE_REVIEW_OUTCOMES:
        acc.output()
    if outcome == 'skipped':
        acc.skip(out['reason'], ticker)
    elif outcome == 'error':
        acc.fail(ticker, out['reason'])
    elif outcome == 'revise' and out['new_plan_id'] is None:
        acc.degrade('revision_failed', f"{ticker}: {(out['detail'] or {}).get('revision_status')}")


# ---------------------------------------------------------------- recheck (spec §8.2, D14)

MIGRATION_MISSING = '迁移 026 未执行'


class RecheckConflict(RuntimeError):
    """A recheck clashes with the chain's state (HTTP 409); ``reason`` is ``chain_not_active``,
    ``agent_unavailable: <reason>`` or ``review_in_progress``. Nothing is written."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _ticker(ticker: Any) -> str:
    identity.stock_id(ticker if isinstance(ticker, str) else '')     # ValueError for anything not a US ticker
    return ticker.strip().upper()


def _require_ready(conn) -> None:
    if not repository.timeline_ready(conn):
        raise service.Unavailable(MIGRATION_MISSING)


def _precheck(ticker: str, signal_date: date, *, session: date, settings, run_lock: bool = True) -> None:
    """§8.2's preconditions in order, in one read-only transaction: migration 026 (Unavailable), the chain
    exists (LookupError) and is entry / holding at S, the agent is available, no review is running on the
    chain (RecheckConflict): neither its write lock nor — with ``run_lock`` — its run lock is held. Both
    locks are only tried and released again; the recheck itself takes the run lock for its whole run."""
    with service.read_only_tx() as conn:
        _require_ready(conn)
        status = service.chain_status(conn, ticker, signal_date, session=session)
        if status is None:
            raise LookupError(f'该单元没有 agent-2 计划链：{ticker} {signal_date}')
        if status['state']['state'] not in ACTIVE_STATES:
            raise RecheckConflict('chain_not_active')
        unavailable = agent_model.unavailable_reason(settings)
        if unavailable is not None:
            raise RecheckConflict(f'agent_unavailable: {unavailable}')
        if not repository.try_review_lock(conn, ticker, signal_date):
            raise RecheckConflict('review_in_progress')
    if run_lock:
        with _run_lock(ticker, signal_date) as got:
            if not got:
                raise RecheckConflict('review_in_progress')


def recheck_check(ticker: str, signal_date: date, *, now: datetime) -> None:
    """The synchronous part of ``POST …/recheck``: raises service.Unavailable (503), LookupError (404),
    ValueError for a bad ticker (400) or RecheckConflict (409); returns None when a recheck may start.
    S is the latest closed trading day at ``now`` (the click time)."""
    ticker = _ticker(ticker)
    _precheck(ticker, signal_date, session=bars_module.latest_closed_session(now),
              settings=agent_model.settings_from_env())


def recheck(ticker: str, signal_date: date, *, now: datetime, deps=None, run_id: str | None = None) -> dict:
    """Review one chain now, on request (spec §8.2): ``trigger = 'recheck'``, cutoff = ``now`` — the click
    time captured by the caller, never when this runs — and S = the latest closed trading day at ``now``.
    The quiet-day maintain (§7.4 step 2) is skipped, so the model is always asked unless a met invalidation
    condition decides it for the host; REVIEW_MAX_ATTEMPTS does not apply, the token cap and quota do.
    New versions get ``origin = 'recheck'``. The chain's run lock is taken first and held to the end (a
    background job may start later than its request: a review that got there first makes this a
    RecheckConflict before any model call), then the preconditions are checked again. A chain that moved
    while the model ran raises RecheckConflict too; its model runs are kept as ``skipped`` runs with their
    tokens. Returns the written plan_reviews row."""
    ticker = _ticker(ticker)
    deps = deps or service.Deps()
    settings = deps.agent_settings if deps.agent_settings is not None else agent_model.settings_from_env()
    session = bars_module.latest_closed_session(now)
    with _run_lock(ticker, signal_date) as got:
        if not got:
            raise RecheckConflict('review_in_progress')
        _precheck(ticker, signal_date, session=session, settings=settings, run_lock=False)
        clock = deps.clock or time.monotonic
        out = _review_chain({'ticker': ticker, 'signal_date': signal_date}, session=session, now=now,
                            trigger='recheck', run_id=run_id, deps=deps, settings=settings, started=clock(),
                            clock=clock, quota={'exhausted': False})
    if 'skipped_without_row' in out:
        raise RecheckConflict(out['skipped_without_row'])
    return out


# ---------------------------------------------------------------- read views (spec §12)

def _run_view(run: dict | None) -> dict | None:
    if run is None:
        return None
    keys = ('id', 'mode', 'agent_version', 'model', 'status', 'reason', 'cutoff_at', 'output', 'counter',
            'input_tokens', 'output_tokens', 'created_at')
    return {**{k: run.get(k) for k in keys}, 'id': str(run['id'])}


def _review_row(row: dict, numbers: dict[str, int]) -> dict:
    """A stored plan_reviews row plus the version numbers it reviewed and produced."""
    new = row.get('new_plan_id')
    return {**row, 'head_version_no': numbers.get(str(row['head_plan_id'])),
            'new_version_no': numbers.get(str(new)) if new is not None else None}


def chain_view(ticker: str, signal_date: date, *, now: datetime) -> dict:
    """One chain read at S = the latest closed trading day at ``now`` (spec §12 GET chains): ``state``
    (``{state, mode, basis}`` of ``timeline.chain_state``), every version (plan row, the generating run's
    output and counter, ``changes``, host ``diff``, the ``plan-shadow-1`` simulation of that version's own
    levels), every review row, and the user inputs that apply to the chain. Read-only, no external source.
    ValueError for a bad ticker, LookupError without an agent-2 chain, Unavailable without migration 026."""
    ticker = _ticker(ticker)
    session = bars_module.latest_closed_session(now)
    with service.read_only_tx() as conn:
        _require_ready(conn)
        status = service.chain_status(conn, ticker, signal_date, session=session)
        if status is None:
            raise LookupError(f'该单元没有 agent-2 计划链：{ticker} {signal_date}')
        head_id = str(status['head']['plan']['id'])
        ticker_bars = repository.read_bars(conn, ticker, session, cutoff_at=now, limit=400)
        spy = repository.read_bars(conn, service.BENCHMARK, session, cutoff_at=now, limit=400)
        splits = repository.split_events(conn, ticker)
        numbers = {str(v['plan_id']): v['version_no'] for v in status['versions']}
        versions = []
        for version in status['versions']:
            plan = repository.plan_by_id(conn, version['plan_id'])
            run = repository.agent_run_by_id(conn, version['agent_run_id'])
            output = (run or {}).get('output') or {}
            versions.append({
                'version_no': version['version_no'], 'plan_id': str(version['plan_id']),
                'origin': version['origin'],
                'supersedes_plan_id': (str(version['supersedes_plan_id'])
                                       if version['supersedes_plan_id'] is not None else None),
                'agent_run_id': str(version['agent_run_id']), 'cutoff_at': version['cutoff_at'],
                'as_of_session': version['as_of_session'], 'created_at': version['created_at'],
                'is_head': str(version['plan_id']) == head_id, 'diff': version['diff'],
                'changes': output.get('changes') or [], 'plan': plan, 'run': _run_view(run),
                'shadow': (plan_shadow_module.simulate(plan, ticker_bars, spy, splits=splits)
                           if plan is not None else None)})
        reviews = [_review_row(row, numbers) for row in status['reviews']]
        inputs = user_inputs.view(user_inputs.ticker_rows(conn, ticker), signal_date)
    return {'ticker': ticker, 'signal_date': signal_date, 'session': session,
            'state': status['state'], 'head_plan_id': head_id,
            'version_no': status['head']['version']['version_no'],
            'latest_review': service._review_view(status['latest_review']),
            'shadow_version': plan_shadow_module.SHADOW_VERSION,
            'versions': versions, 'reviews': reviews, 'inputs': inputs}


def reviews_view(session: date) -> dict:
    """Every review row of review session S (batch and recheck, oldest first) with the version numbers
    it reviewed and produced. Read-only; Unavailable without migration 026."""
    with service.read_only_tx() as conn:
        _require_ready(conn)
        rows = repository.reviews_on(conn, session)
        numbers: dict[str, int] = {}
        for row in rows:
            for plan_id in (row['head_plan_id'], row['new_plan_id']):
                if plan_id is not None and str(plan_id) not in numbers:
                    version = repository.version_by_plan(conn, plan_id)
                    if version is not None:
                        numbers[str(plan_id)] = version['version_no']
    return {'session': session, 'reviews': [_review_row(row, numbers) for row in rows]}


def ticker_chains(ticker: str, *, now: datetime) -> dict:
    """Every agent-2 chain of one ticker (ended ones included), newest signal date first, read at S = the
    latest closed trading day at ``now`` (spec §11 「标的」页): ``{ticker, chains: [{signal_date, state,
    mode, version_no, head_plan_id, latest_review: {outcome, decided_by, created_at, reason} | None}]}``.
    Read-only; ValueError for a bad ticker, Unavailable without migration 026."""
    ticker = _ticker(ticker)
    session = bars_module.latest_closed_session(now)
    rows = []
    with service.read_only_tx() as conn:
        _require_ready(conn)
        book = service._book(conn, ticker)
        for chain in repository.all_chains(conn):
            if chain['ticker'].upper() != ticker:
                continue
            status = service.chain_status(conn, ticker, chain['signal_date'], session=session, book=book)
            if status is None:
                continue
            latest = status['latest_review']
            rows.append({'signal_date': chain['signal_date'], 'state': status['state']['state'],
                         'mode': status['state']['mode'], 'version_no': status['head']['version']['version_no'],
                         'head_plan_id': str(status['head']['plan']['id']),
                         'latest_review': ({'outcome': latest['outcome'], 'decided_by': latest['decided_by'],
                                            'created_at': latest['created_at'], 'reason': latest['reason']}
                                           if latest is not None else None)})
    rows.sort(key=lambda r: r['signal_date'], reverse=True)
    return {'ticker': ticker, 'chains': rows}


# ---------------------------------------------------------------- check (spec §12)

_CALL_REF = re.compile(r'call:(\d+)')
_USER_REF = re.compile(r'user:(\d+)')


def _refs_in(value: Any) -> list[str]:
    """Every string under a ``refs`` key, anywhere in an output / counter JSON."""
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, inner in item.items():
                if key == 'refs' and isinstance(inner, list):
                    found.extend(str(ref) for ref in inner)
                else:
                    walk(inner)
        elif isinstance(item, list):
            for inner in item:
                walk(inner)

    walk(value)
    return found


def _ref_problem(ref: str, *, calls: set[int], inputs: dict[int, dict], cutoff: datetime) -> str | None:
    """None when ``ref`` holds: ``call:N`` is a tool call of the run itself, ``user:<id>`` an input of the
    ticker created at or before ``cutoff``."""
    if match := _CALL_REF.fullmatch(ref):
        return None if int(match.group(1)) in calls else f'引用 {ref} 不是生成运行的工具调用'
    if match := _USER_REF.fullmatch(ref):
        row = inputs.get(int(match.group(1)))
        if row is None:
            return f'引用 {ref} 不是该标的的用户输入'
        if row['created_at'] > cutoff:
            return (f"引用 {ref} 晚于截止时间（created_at {row['created_at'].isoformat()} > "
                    f'cutoff_at {cutoff.isoformat()}）')
        return None
    return f'引用 {ref} 无法识别'


def _stage_evidence(conn, session: date) -> tuple[datetime | None, dict[tuple[str, str], list[str]]]:
    """(batch start, exclusions) of S from the ``review`` stage rows: the earliest review-stage start time
    (None without stage rows) and (ticker, signal_date ISO) -> the reasons the stage did not review that
    chain (``detail.excluded``: fresh_version, already_reviewed, object_cap and the row-less skips)."""
    if not repository.stage_runs_ready(conn):
        return None, {}
    start: datetime | None = None
    out: dict[tuple[str, str], list[str]] = {}
    for row in repository.stage_runs_for_session(conn, session):
        if row['stage'] != 'review':
            continue
        if row['started_at'] is not None and (start is None or row['started_at'] < start):
            start = row['started_at']
        for item in (row.get('detail') or {}).get('excluded') or []:
            out.setdefault((str(item['ticker']).upper(), str(item['signal_date'])), []).append(item['reason'])
    return start, out


def _before_batch(version: dict, session: date, batch_start: datetime | None) -> bool:
    """Whether the version existed when the batch reviewed session S: anything generated before S, the
    signal-day version 0 of S, and a recheck version of S written before the batch started. Without any
    evidence of the batch's start, a recheck version of S is not taken as the batch's input (it must not
    mask a missing batch review). A batch review's own version (origin review, as_of S) is its output."""
    if version['as_of_session'] < session:
        return True
    if version['as_of_session'] > session:
        return False
    if version['origin'] == 'signal':
        return True
    return version['origin'] == 'recheck' and batch_start is not None and version['created_at'] < batch_start


def _check_chain(conn, chain: dict, session: date, *, stage_start: datetime | None,
                 excluded: dict[tuple[str, str], list[str]], out: Callable[[str], None]) -> str | None:
    """One chain's completeness on S: 'complete', 'fresh', 'missing' or None (not due)."""
    ticker, signal_date = chain['ticker'], chain['signal_date']
    versions = repository.chain_versions(conn, ticker, signal_date)
    reviews = repository.chain_reviews(conn, ticker, signal_date)
    batch = [r for r in reviews if r['session'] == session and r['trigger'] == 'batch']
    batch_start = stage_start or min((r['created_at'] for r in batch), default=None)
    known = [v for v in versions if _before_batch(v, session, batch_start)]
    if not known:
        return None                                       # the chain was born after S
    head = max(known, key=lambda v: v['version_no'])
    tag = f"{ticker} {signal_date} 第 {head['version_no']} 版"
    if head['as_of_session'] == session:
        out(f'  {tag}：当天生成（fresh_version）')
        return 'fresh'
    prior = [r for r in reviews if r['session'] < session or (
        r['session'] == session and r['trigger'] == 'recheck' and batch_start is not None
        and r['created_at'] < batch_start)]
    state = timeline.chain_state(
        versions=known, head_plan=repository.plan_by_id(conn, head['plan_id']), reviews=prior,
        decision=repository.decision_head(conn, ticker, signal_date),
        unit_buys=service.unit_buys(conn, ticker, signal_date), open_lots=service._book(conn, ticker)['open'],
        session=session, legacy=False)['state']
    if state not in ACTIVE_STATES:
        out(f'  {tag}：{state}，不需复查')
        return None
    reasons = excluded.get((ticker.upper(), signal_date.isoformat()), [])
    if 'object_cap' in reasons:
        out(f'  {tag} {state}：超出复查上限（object_cap）')
        return None
    effective = [r for r in batch if r['outcome'] in repository.EFFECTIVE_REVIEW_OUTCOMES]
    if len(effective) == 1:
        out(f"  {tag} {state}：有效批处理复查 1 条（{effective[0]['outcome']}）")
        return 'complete'
    why = [f"{'' if r['trigger'] == 'batch' else '重新复查 '}{r['outcome']}（{r['reason']}）"
           for r in reviews if r['session'] == session and r['outcome'] not in repository.EFFECTIVE_REVIEW_OUTCOMES]
    why += [f'阶段跳过（{reason}）' for reason in reasons]
    if len(effective) > 1:
        why.insert(0, f'有效批处理复查 {len(effective)} 条')
    out(f"缺有效复查  {tag} {state}：{'；'.join(why) or '无复查记录'}")
    return 'missing'


def _check_versions(conn, session: date, inputs_of: Callable[[str], dict[int, dict]]) -> tuple[int, list[str]]:
    """(new versions of S, problems): each version generated on S points at the previous version, carries
    its generating run's cutoff_at, and every ref of that run's output and counter holds; every review row
    of S cites only its own review run's calls and inputs created by its cutoff."""
    problems: list[str] = []
    count = 0
    for chain in repository.all_chains(conn):
        ticker, signal_date = chain['ticker'], chain['signal_date']
        versions = repository.chain_versions(conn, ticker, signal_date)
        by_no = {v['version_no']: v for v in versions}
        for version in versions:
            if version['as_of_session'] != session:
                continue
            count += 1
            tag = f"{ticker} {signal_date} 第 {version['version_no']} 版 {str(version['plan_id'])[:8]}"
            previous = by_no.get(version['version_no'] - 1)
            expected = str(previous['plan_id']) if previous is not None else None
            actual = str(version['supersedes_plan_id']) if version['supersedes_plan_id'] is not None else None
            if version['version_no'] >= 1 and actual != expected:
                problems.append(f'{tag}：supersedes_plan_id 没有指向上一版')
            run = repository.agent_run_by_id(conn, version['agent_run_id'])
            if run is None or run['cutoff_at'] != version['cutoff_at']:
                problems.append(f'{tag}：cutoff_at 与生成运行不一致')
            if run is None:
                continue
            calls = {c['seq'] for c in repository.agent_tool_calls(conn, run['id'])}
            for ref in _refs_in(run['output']) + _refs_in(run['counter']):
                if problem := _ref_problem(ref, calls=calls, inputs=inputs_of(ticker), cutoff=version['cutoff_at']):
                    problems.append(f'{tag}：{problem}')
    for row in repository.reviews_on(conn, session):
        tag = f"{row['ticker']} {row['signal_date']} 复查 {row['id']}"
        calls = ({c['seq'] for c in repository.agent_tool_calls(conn, row['review_agent_run_id'])}
                 if row['review_agent_run_id'] is not None else set())
        refs = [str(r) for r in row['refs'] or []] + [f'user:{i}' for i in row['user_input_ids'] or []]
        for ref in refs:
            if problem := _ref_problem(ref, calls=calls, inputs=inputs_of(row['ticker']), cutoff=row['cutoff_at']):
                problems.append(f'{tag}：{problem}')
    return count, problems


def check(session: date, out: Callable[[str], None] = print) -> int:
    """§12 ``check --session``: every chain due on S — entry / holding as of the head the batch saw (the
    batch's start is the review stage row's ``started_at``, else its first review row), not generated on S
    (``fresh_version``, accepted) and not capped (``object_cap`` in the stage's ``detail.excluded``) — has
    exactly one effective batch review; plus the version and ref checks of ``_check_versions``. 0 when everything holds, 1
    otherwise. Read-only; Unavailable (exit 2 in ``main``) without a database or migration 026.
    Decisions and fills are read as stored (the same reading as the review stage)."""
    cache: dict[str, dict[int, dict]] = {}
    with service.read_only_tx() as conn:
        _require_ready(conn)

        def inputs_of(ticker: str) -> dict[int, dict]:
            if ticker not in cache:
                cache[ticker] = {row['id']: row for row in user_inputs.ticker_rows(conn, ticker)}
            return cache[ticker]

        stage_start, excluded = _stage_evidence(conn, session)
        out(f'复查完整性 {session}')
        verdicts = [_check_chain(conn, chain, session, stage_start=stage_start, excluded=excluded, out=out)
                    for chain in repository.all_chains(conn)]
        new_versions, problems = _check_versions(conn, session, inputs_of)
    for problem in problems:
        out(f'问题  {problem}')
    complete, missing, fresh = (verdicts.count(v) for v in ('complete', 'missing', 'fresh'))
    passed = not missing and not problems
    out(f"汇总：{session} 应复查 {complete + missing} 条，齐全 {complete} 条，缺 {missing} 条；当天生成 {fresh} 条；"
        f"新版 {new_versions} 份，问题 {len(problems)} 处 → {'通过' if passed else '不通过'}")
    return 0 if passed else 1


# ---------------------------------------------------------------- command line (spec §12)

def _cli_now() -> datetime:
    return datetime.now(UTC)


def _cli_deps():
    return service.Deps()


def _date_arg(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'日期格式应为 YYYY-MM-DD：{text}') from None


def _ticker_arg(text: str) -> str:
    try:
        return _ticker(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'不是美股代码：{text}') from None


def _money(value: Any) -> str:
    return '-' if value is None else f'{Decimal(str(value)):.2f}'


def _beijing(moment: datetime | None) -> str:
    from investment_assistant.workbench.review_digest import SH      # the workbench's Beijing-time constant

    return moment.astimezone(SH).strftime('%Y-%m-%d %H:%M') if moment is not None else '-'


def _chain_cmd(args: argparse.Namespace, out: Callable[[str], None]) -> int:
    try:
        view = chain_view(args.ticker, args.date, now=_cli_now())
    except LookupError as exc:
        out(str(exc))
        return 1
    state = view['state']
    out(f"链 {view['ticker']} {view['signal_date']}  状态 {state['state']}（{state['basis']}）  "
        f"复查交易日 {view['session']}  最新第 {view['version_no']} 版")
    for v in view['versions']:
        plan = v['plan'] or {}
        shadow = (v['shadow'] or {}).get('status', '-')
        out(f"第 {v['version_no']} 版  {v['origin']}  {v['plan_id'][:8]}  生成 {_beijing(v['created_at'])}  "
            f"截止 {_beijing(v['cutoff_at'])}  入场 {_money(plan.get('entry_low'))}–{_money(plan.get('entry_high'))}  "
            f"止损 {_money(plan.get('stop'))}  T1 {_money(plan.get('target1'))}  "
            f"有效 {plan.get('valid_from')}…{plan.get('valid_until')}  {plan.get('status')}  影子 {shadow}")
        if v['diff']:
            out('  差异：' + '；'.join(f"{d['field']} {d['before']} → {d['after']}" for d in v['diff']))
    for r in view['reviews']:
        produced = f" → 第 {r['new_version_no']} 版" if r['new_version_no'] is not None else ''
        failed = (r['detail'] or {}).get('revision_status')
        out(f"复查 {r['session']}  {r['trigger']}  {r['outcome']}（{r['decided_by']}）  第 {r['head_version_no']} 版"
            f"{produced}  {r['reason']}{f'  修订未通过：{failed}' if failed else ''}")
    for row in view['inputs']:
        body = ' '.join(row['body'].split())[:40]
        out(f"输入 {row['ref']}  {row['kind']}  {row['status']}  {_beijing(row['created_at'])}  {body}")
    return 0


def _recheck_cmd(args: argparse.Namespace, out: Callable[[str], None]) -> int:
    run_id = f'plan_recheck-cli-{uuid.uuid4().hex[:8]}'
    try:
        row = recheck(args.ticker, args.date, now=_cli_now(), deps=_cli_deps(), run_id=run_id)
    except (RecheckConflict, LookupError) as exc:
        out(f'不能重新复查：{exc}')
        return 1
    out(f"复查记录 {row['id']}  {row['session']}  {row['outcome']}（{row['decided_by']}）  {row['reason']}")
    out(f"新版：{row['new_plan_id'] or '无'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """``chain`` prints one chain (read-only; 1 without a chain); ``recheck`` reviews one chain now
    (writes; 1 on a 409-type conflict or without a chain); ``check`` verifies one session's reviews
    (read-only; 1 on any violation). Exit 2 for bad arguments (argparse, including a ticker that is not a US
    ticker) or an unavailable database / migration 026; any other error is a bug and propagates."""
    parser = argparse.ArgumentParser(prog='python -m investment_assistant.workbench.plan_review',
                                     description='Agent 计划链：查看、重新复查与复查完整性核对。')
    commands = parser.add_subparsers(dest='command', required=True)
    for name, text in (('chain', '打印链状态、各版本与复查记录（只读）'), ('recheck', '立即重新复查一条链（写）')):
        sub = commands.add_parser(name, help=text)
        sub.add_argument('--ticker', type=_ticker_arg, required=True, help='标的')
        sub.add_argument('--date', type=_date_arg, required=True, help='信号日，YYYY-MM-DD')
    checker = commands.add_parser('check', help='核对一个交易日的复查完整性（只读）')
    checker.add_argument('--session', type=_date_arg, required=True, help='复查交易日，YYYY-MM-DD')
    args = parser.parse_args(argv)
    try:
        if args.command == 'check':
            return check(args.session, print)
        return (_chain_cmd if args.command == 'chain' else _recheck_cmd)(args, print)
    except service.Unavailable as exc:
        print(f'数据库不可用：{exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
