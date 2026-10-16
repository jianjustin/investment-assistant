"""Manual research job with durable existing run reports; never notifies."""
from investment_assistant.config import load_config
from investment_assistant.tasks._harness import run_task
from investment_assistant.us_research import service


def _failure():
    return {'results': [], 'errors': [{'error': '美股研究任务失败，请检查本地来源与数据库配置'}],
            'notifications': 'disabled'}


def run(config=None, *, symbols=None, datasets=None, retry_failed=False, trigger_source='manual'):
    def core():
        try:
            return service.sync(symbols, datasets=datasets, retry_failed=retry_failed, config=effective_config)
        except Exception:
            # The harness records exception text; never pass unsanitized failures.
            return _failure()
    try:
        effective_config = config if config is not None else load_config()
        return run_task('us-research', core, config=effective_config,
                        trigger_source=trigger_source, notify=False)
    except Exception:
        # Also cover configuration/report-storage failures before runner sees them.
        return {'task': 'us-research', 'status': 'error', 'summary': _failure()}
