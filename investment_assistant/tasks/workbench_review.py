"""The workbench_review task: freeze and push weekly/monthly reviews, remind for missing month-end snapshots."""
from __future__ import annotations

from datetime import UTC, datetime

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task
from investment_assistant.workbench import service


def run(config: AssistantConfig | None = None, *, trigger_source: str = 'scheduled',
        now: datetime | None = None, client=None):
    effective = config if config is not None else load_config()
    moment = now or datetime.now(UTC)

    def tick() -> dict:
        from investment_assistant.services.settings import effective_notify_config
        notify_cfg = effective_notify_config(effective.notify)
        return service.review_tick(now=moment, notify_cfg=notify_cfg,
                                   trigger_source=trigger_source, client=client)

    return run_task('workbench_review', tick, config=effective, trigger_source=trigger_source, notify=False)
