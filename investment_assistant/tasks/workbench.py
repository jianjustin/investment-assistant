"""Daily US workbench batch: collect, evaluate rules, plan, brief, push. Never trades."""
from __future__ import annotations

from datetime import UTC, datetime

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task
from investment_assistant.workbench import service


def run(config: AssistantConfig | None = None, *, trigger_source: str = 'scheduled', now: datetime | None = None,
        deps: service.Deps | None = None):
    effective = config if config is not None else load_config()
    moment = now or datetime.now(UTC)
    # Scheduled runs skip New York holidays; a manual run always targets the latest settled session.
    def batch() -> dict:
        # The batch reads its tiered pool from the watchlist table; the config watchlist stays for other tasks.
        summary = service.run_batch(now=moment, deps=deps,
                                    skip_non_trading=trigger_source == 'scheduled')
        if trigger_source != 'scheduled':
            return summary  # 手动运行不推送
        from investment_assistant.services.settings import effective_notify_config
        notify_cfg = effective_notify_config(effective.notify)
        if summary.get('status') == 'skipped':
            summary['push'] = service.push_closed(now=moment, notify_cfg=notify_cfg)
        else:
            summary['push'] = service.push(now=moment, force=False, summary=summary, notify_cfg=notify_cfg)
        return summary

    return run_task('workbench', batch, config=effective, trigger_source=trigger_source, notify=False)
