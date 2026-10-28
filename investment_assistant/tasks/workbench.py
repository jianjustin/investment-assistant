"""Daily US workbench batch: collect, evaluate rules, plan, brief, push. Never trades."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task
from investment_assistant.workbench import bars, families, repository, service
from investment_assistant.workbench import stages as stages_module


def _timeline_ready() -> bool:
    """Migration 026 present (v2.5 D22), read on a read-only transaction; any failure counts as not ready."""
    try:
        with service.read_only_tx() as conn:
            return repository.timeline_ready(conn)
    except Exception:  # noqa: BLE001 - an unreadable database is booked as stages-1; the batch reports it
        return False


def _account_push(recorder: stages_module.StageRecorder, acc: stages_module.StageAcc,
                  out: dict[str, Any]) -> None:
    """Close the push stage from the notifier's result (v2.4 §4): a skip for the three
    non-events, success for sent / no_notifications, failed for every other reason.

    The notifier reports only the messages actually sent, so input equals output here."""
    reason = out.get('reason')
    if not out.get('sent') and reason in ('already_pushed', 'task_disabled'):
        recorder.skip('push', reason)
        return
    messages = int(out.get('messages') or 0)
    acc.input(messages)
    acc.output(messages)
    acc.set_ref('push', {'sent': bool(out.get('sent')), 'messages': messages,
                         'reason': families.sanitize_reason(reason) if reason else None})
    if out.get('sent') or reason == 'no_notifications':
        recorder.finish('push')
    else:
        recorder.finish('push', failed=str(reason or 'not_sent'))


def run(config: AssistantConfig | None = None, *, trigger_source: str = 'scheduled', now: datetime | None = None,
        deps: service.Deps | None = None):
    effective = config if config is not None else load_config()
    moment = now or datetime.now(UTC)
    scheduled = trigger_source == 'scheduled'
    # Scheduled runs skip New York holidays; a manual run always targets the latest settled session.
    def batch(run_id: str) -> dict:
        # 阶段证据（v2.4 §4，v2.5 §7.1）：任务层建记录器，批处理记推送之前的阶段，推送阶段在这里记。
        # 迁移 026 未执行（D22）→ 本次按 stages-1 记 7 行；就绪 → stages-2 记 8 行。
        ready = _timeline_ready()
        recorder = stages_module.StageRecorder(run_id, 'scheduled' if scheduled else 'manual_batch',
                                               bars.latest_closed_session(moment),
                                               version=stages_module.STAGES_VERSION if ready
                                               else stages_module.STAGES_VERSION_V1)
        failure: BaseException | None = None
        summary: dict | None = None
        try:
            # The batch reads its tiered pool from the watchlist table; the config watchlist stays for other tasks.
            # run_id 来自任务外壳，data_fetch_runs / screen_runs / signal_candidates 与 job_reports 同源（v2.4 §6.1）。
            summary = service.run_batch(now=moment, deps=deps, run_id=run_id,
                                        skip_non_trading=scheduled,
                                        record_trigger='scheduled' if scheduled else 'manual_batch',
                                        stages=recorder, timeline_ready=ready)
            if not scheduled:
                recorder.skip('push', 'manual_run')
                return summary  # 手动运行不推送
            from investment_assistant.services.settings import effective_notify_config
            notify_cfg = effective_notify_config(effective.notify)
            closed = summary.get('status') == 'skipped'
            acc = recorder.open('push')
            if closed:
                acc.detail['closed'] = True
            try:
                with acc.timing():
                    if closed:
                        summary['push'] = service.push_closed(now=moment, notify_cfg=notify_cfg)
                    else:
                        summary['push'] = service.push(now=moment, force=False, summary=summary,
                                                       notify_cfg=notify_cfg)
            except BaseException as exc:
                recorder.finish('push', failed=f'aborted: {exc}')
                raise
            _account_push(recorder, acc, summary['push'])
            return summary
        except BaseException as exc:
            failure = exc
            raise
        finally:
            stage_status = recorder.close(failure)
            if failure is None and summary is not None:
                summary['stage_status'] = stage_status

    return run_task('workbench', batch, config=effective, trigger_source=trigger_source, notify=False,
                    pass_run_id=True)
