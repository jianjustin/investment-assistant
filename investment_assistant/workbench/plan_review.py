"""The daily review stage `review` and the per-chain review use case (v2.5 spec §7, `stages-2`).

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
"""
from __future__ import annotations

import os
import uuid
from contextlib import ExitStack
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable

from investment_assistant.workbench import families, repository, service, timeline
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
    ``{'skips': [(reason, ticker)], 'ended': {expired, closed_by_decision, position_closed},
    'failures': [(ticker, reason)], 'holdings_without_chain': [ticker]}`` (held tickers without a chain in
    the holding state, D7). A chain whose reading raises is read under a savepoint and only listed in
    ``failures``; the other chains go on.
    Records are read as stored; ``now`` is the batch cutoff, kept for symmetry with the other readers."""
    objects: list[dict] = []
    skips: list[tuple[str, str]] = []
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
        if obj['as_of_session'] == session:
            skips.append(('fresh_version', obj['ticker']))
            continue
        if reviewed:
            skips.append(('already_reviewed', obj['ticker']))
            continue
        objects.append(obj)
    objects.sort(key=_order)
    skips += [('object_cap', obj['ticker']) for obj in objects[REVIEW_MAX_OBJECTS:]]
    held = repository.open_position_tickers(conn)
    return objects[:REVIEW_MAX_OBJECTS], {'skips': skips, 'ended': ended, 'failures': failures,
                                          'holdings_without_chain': sorted(held - holding)}


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

def review_chain(obj: dict, *, session: date, now: datetime, trigger: str, run_id: str | None, deps, settings,
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
            return _commit(seen, ticker=ticker, signal_date=signal_date, session=session, trigger=trigger,
                           build=build)
        except service.Unavailable:
            raise
        except Exception as exc:      # the write failed and rolled back: record it, so attempts and tokens count
            return _commit(seen, ticker=ticker, signal_date=signal_date, session=session, trigger=trigger,
                           build=lambda conn, attempt: _write_failed(conn, attempt, exc=exc, base=base,
                                                                     spent=spent, run_row=run_row,
                                                                     settings=settings))

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
