"""Decisions and trades, append-only (design §4.6, §4.7, §11).

A unit's decisions form a chain: the first has no supersedes_id, each correction
must supersede the current head. Trades are only ever voided, never edited.
Retrying a request_id with the same content returns the original record.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from investment_assistant.workbench import positions, repository

ACTIONS = ('buy', 'sell', 'watch')
FINAL_ACTIONS = ('buy', 'sell', 'watch', 'ignore')


class LedgerError(ValueError):
    """Invalid request (HTTP 400)."""


class Conflict(Exception):
    """Request clashes with stored state (HTTP 409)."""


class NotFound(LookupError):
    """Unknown record (HTTP 404)."""


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, (uuid.UUID, date, datetime)):
        return value.isoformat() if not isinstance(value, uuid.UUID) else str(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def request_hash(record: dict[str, Any]) -> str:
    body = {k: _plain(v) for k, v in record.items() if k != 'request_id'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _uuid(value: Any, field: str, *, optional: bool = False) -> uuid.UUID | None:
    if value in (None, '') and optional:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise LedgerError(f'{field} must be a UUID') from None


def _choice(value: Any, field: str, options: tuple[str, ...]) -> str:
    if value not in options:
        raise LedgerError(f"{field} must be one of {', '.join(options)}")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f'{field} is required')
    return value.strip()


def _ticker(value: Any) -> str:
    return _text(value, 'ticker').upper()


def _decimal(value: Any, field: str, *, minimum: Decimal, inclusive: bool) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise LedgerError(f'{field} must be a number') from None
    if not number.is_finite() or (number < minimum if inclusive else number <= minimum):
        raise LedgerError(f"{field} must be {'>=' if inclusive else '>'} {minimum}")
    return number


def _own_plan(value: Any) -> dict[str, Any] | None:
    if value in (None, ''):
        return None
    if not isinstance(value, dict):
        raise LedgerError('own_plan must be an object')
    from investment_assistant.workbench import plans as _plans

    try:
        levels = _plans.validate_levels(value)
    except ValueError as exc:
        raise LedgerError(str(exc)) from None
    return {'request_id': _uuid(value.get('request_id'), 'own_plan.request_id'), **levels}


def validate_decision(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        signal_date = date.fromisoformat(str(payload.get('signal_date')))
    except ValueError:
        raise LedgerError('signal_date must be YYYY-MM-DD') from None
    candidate_ids = payload.get('candidate_ids')
    if not isinstance(candidate_ids, list) or not candidate_ids:
        raise LedgerError('candidate_ids must be a non-empty list')
    rec = {
        'request_id': _uuid(payload.get('request_id'), 'request_id'),
        'ticker': _ticker(payload.get('ticker')),
        'signal_date': signal_date,
        'candidate_ids': sorted({_uuid(c, 'candidate_ids') for c in candidate_ids}, key=str),
        'brief_id': _uuid(payload.get('brief_id'), 'brief_id', optional=True),
        'proposed_action': _choice(payload.get('proposed_action'), 'proposed_action', ACTIONS),
        'final_action': _choice(payload.get('final_action'), 'final_action', FINAL_ACTIONS),
        'decision': _choice(payload.get('decision'), 'decision', ('accept', 'reject', 'downgrade')),
        'reason': _text(payload.get('reason'), 'reason'),
        'supersedes_id': _uuid(payload.get('supersedes_id'), 'supersedes_id', optional=True),
        'plan_id': _uuid(payload.get('plan_id'), 'plan_id', optional=True),
        'own_plan': _own_plan(payload.get('own_plan')),
    }
    if rec['plan_id'] is not None and rec['own_plan'] is not None:
        raise LedgerError('plan_id 与 own_plan 只能二选一')
    if rec['decision'] != 'accept' and (rec['plan_id'] is not None or rec['own_plan'] is not None):
        raise LedgerError('否则决与降级不需要计划')
    expected = {'accept': rec['proposed_action'], 'reject': 'ignore', 'downgrade': 'watch'}[rec['decision']]
    if rec['final_action'] != expected or (rec['decision'] == 'downgrade' and rec['proposed_action'] == 'watch'):
        raise LedgerError(f"{rec['decision']} of {rec['proposed_action']} cannot end as {rec['final_action']}")
    return rec


def validate_trade(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    try:
        executed_at = datetime.fromisoformat(str(payload.get('executed_at')))
    except ValueError:
        raise LedgerError('executed_at must be an ISO timestamp') from None
    if executed_at.tzinfo is None or executed_at.utcoffset() is None:
        raise LedgerError('executed_at must include a timezone')
    if executed_at > now:
        raise LedgerError('executed_at cannot be in the future')
    note = payload.get('note')
    return {
        'request_id': _uuid(payload.get('request_id'), 'request_id'),
        'ticker': _ticker(payload.get('ticker')),
        'side': _choice(payload.get('side'), 'side', ('buy', 'sell')),
        'quantity': _decimal(payload.get('quantity'), 'quantity', minimum=Decimal(0), inclusive=False),
        'price': _decimal(payload.get('price'), 'price', minimum=Decimal(0), inclusive=False),
        'fee': _decimal(payload.get('fee', 0) or 0, 'fee', minimum=Decimal(0), inclusive=True),
        'executed_at': executed_at,
        'decision_id': _uuid(payload.get('decision_id'), 'decision_id', optional=True),
        'note': note.strip() if isinstance(note, str) and note.strip() else None,
    }


def _replay(existing: dict[str, Any] | None, digest: str) -> dict[str, Any] | None:
    if existing is None:
        return None
    if existing['request_hash'] != digest:
        raise Conflict('request_id was already used with different content')
    return {'status': 'existing', 'record': existing}


def record_decision(conn, payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    rec = validate_decision(payload)
    digest = request_hash(rec)
    repository.lock(conn, f"decision:{rec['ticker']}:{rec['signal_date']}")
    if replay := _replay(repository.decision_by_request(conn, rec['request_id']), digest):
        return replay
    if repository.count_unit_candidates(conn, rec['ticker'], rec['signal_date'], rec['candidate_ids']) != len(rec['candidate_ids']):
        raise LedgerError('candidate_ids must all belong to this ticker and signal_date')
    if rec['brief_id'] and not repository.brief_in_unit(conn, rec['brief_id'], rec['ticker'], rec['signal_date']):
        raise LedgerError('brief_id does not belong to this unit')
    head = repository.decision_head(conn, rec['ticker'], rec['signal_date'])
    if head is None and rec['supersedes_id'] is not None:
        raise LedgerError('nothing to supersede in this unit')
    if head is not None and rec['supersedes_id'] != head['id']:
        raise Conflict('this unit already has a newer decision; supersede the latest one')
    rule = repository.rule_plan(conn, rec['ticker'], rec['signal_date'])
    plan_id = _checked_plan_id(conn, rec, rule)
    if rec['own_plan'] is not None:
        plan_id = _record_own_plan(conn, rec, rule, now=now)['id']
    rec = {**rec, 'plan_id': plan_id}
    return {'status': 'created', 'record': repository.insert_decision(conn, rec, digest, decided_at=now)}


def _checked_plan_id(conn, rec: dict[str, Any], rule: dict[str, Any] | None):
    """spec §5.3: what an accept of a buy unit must carry, and what plan_id may point to."""
    needs_plan = rec['decision'] == 'accept' and rec['proposed_action'] == 'buy'
    if needs_plan and rule is not None:
        if rule['status'] == 'ok':
            if rec['plan_id'] is None and rec['own_plan'] is None:
                raise LedgerError('采纳买入必须携带规则计划（plan_id）或自定价位（own_plan）')
            if rec['plan_id'] is not None and rec['plan_id'] != rule['id']:
                raise LedgerError('plan_id 必须指向该单元当前规则计划，或改用自定价位')
        elif rec['plan_id'] is not None:
            raise LedgerError('规则计划已作废，只能采纳自定价位（own_plan）')
    if rec['plan_id'] is not None:
        linked = repository.plan_by_id(conn, rec['plan_id'])
        if linked is None or linked['ticker'] != rec['ticker'] or linked['signal_date'] != rec['signal_date']:
            raise LedgerError('plan_id 不属于该决策单元')
    return rec['plan_id']


def _record_own_plan(conn, rec: dict[str, Any], rule: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Build and store the own plan in this decision's transaction; replay by request_id is idempotent."""
    from investment_assistant.config import load_config
    from investment_assistant.workbench import plans as _plans, service as _service

    bars = repository.read_bars(conn, rec['ticker'], rec['signal_date'], cutoff_at=now)
    if not bars:
        raise LedgerError('该单元缺少 K 线，无法生成自定计划')
    plan = _plans.build_own_plan(
        rule_plan=rule, levels={k: rec['own_plan'][k] for k in ('entry_low', 'entry_high', 'stop', 'target1')},
        ticker=rec['ticker'], signal_date=rec['signal_date'], bars=bars,
        earnings_row=repository.latest_earnings(conn, rec['ticker'], cutoff_at=now),
        snapshot=repository.snapshot_at(conn, rec['signal_date'], cutoff_at=now),
        exposure=_service.exposure(conn, rec['signal_date'], cutoff_at=now, ticker=rec['ticker']),
        params=load_config().workbench)
    plan = {**plan, 'request_id': rec['own_plan']['request_id'], 'request_hash': request_hash(plan)}
    existing = repository.plan_by_request(conn, plan['request_id'])
    if existing is not None:
        if existing['request_hash'] != plan['request_hash']:
            raise Conflict('own_plan.request_id 已用于不同内容')
        return existing
    return repository.insert_plan(conn, plan)


def _check_book(conn, ticker: str, trades: list[dict[str, Any]]) -> None:
    try:
        positions.build(trades, splits=repository.split_events(conn, ticker))
    except positions.PositionError as exc:
        raise LedgerError(str(exc)) from None


def record_trade(conn, payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    rec = validate_trade(payload, now=now)
    digest = request_hash(rec)
    repository.lock(conn, f"trades:{rec['ticker']}")
    if replay := _replay(repository.trade_by_request(conn, rec['request_id']), digest):
        return replay
    if rec['decision_id'] is not None:
        decision = repository.decision_by_id(conn, rec['decision_id'])
        if decision is None or decision['ticker'] != rec['ticker']:
            raise LedgerError('decision_id must refer to a decision for the same ticker')
    _check_book(conn, rec['ticker'], [*repository.list_trades(conn, rec['ticker']), {**rec, 'id': 'new', 'voided_at': None}])
    return {'status': 'created', 'record': repository.insert_trade(conn, rec, digest, recorded_at=now)}


def void_trade(conn, trade_id: Any, reason: Any, *, now: datetime) -> dict[str, Any]:
    reason = _text(reason, 'void_reason')
    trade = repository.trade_by_id(conn, _uuid(trade_id, 'trade_id'))
    if trade is None:
        raise NotFound('trade not found')
    repository.lock(conn, f"trades:{trade['ticker']}")
    trade = repository.trade_by_id(conn, trade['id'])
    if trade['voided_at'] is not None:
        raise Conflict('trade is already voided')
    _check_book(conn, trade['ticker'], [t for t in repository.list_trades(conn, trade['ticker']) if t['id'] != trade['id']])
    return repository.mark_trade_voided(conn, trade['id'], reason, voided_at=now)
