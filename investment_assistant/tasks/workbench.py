"""Daily US workbench batch: collect, evaluate rules, brief. Never notifies, never trades."""
from __future__ import annotations

from datetime import UTC, datetime

from investment_assistant.ashare.domain import us_only
from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.tasks._harness import run_task
from investment_assistant.workbench import service


def run(config: AssistantConfig | None = None, *, trigger_source: str = 'scheduled', now: datetime | None = None,
        deps: service.Deps | None = None):
    effective = config if config is not None else load_config()
    moment = now or datetime.now(UTC)
    # Scheduled runs skip New York holidays; a manual run always targets the latest settled session.
    return run_task('workbench',
                    lambda: service.run_batch(tickers=us_only(effective.watchlist), now=moment, deps=deps,
                                              skip_non_trading=trigger_source == 'scheduled'),
                    config=effective, trigger_source=trigger_source, notify=False)
