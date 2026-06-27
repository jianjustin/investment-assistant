from unittest.mock import patch
from investment_assistant.config import AssistantConfig
from investment_assistant.tasks import daily


def test_daily_writes_run_log_and_tolerates_filing_failure():
    cfg = AssistantConfig()
    with patch("investment_assistant.tasks.daily.append_run") as append, \
         patch("investment_assistant.hermes.daily.run_daily", return_value={"run_id": "x", "status": "success"}) as rd:
        out = daily.run(cfg)
    assert out["status"] == "success"
    append.assert_called_once()
