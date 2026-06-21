from dataclasses import replace

from investment_assistant.config import AssistantConfig
from investment_assistant.hermes.daily import run_daily


def test_run_daily_orchestrates_market_filings_and_brief(tmp_path):
    calls = []
    cfg = replace(AssistantConfig(), filings=replace(AssistantConfig().filings, output_dir=tmp_path / "filings"))

    def market_step(config, run_id):
        calls.append(("market", run_id))
        return {"market_status": "green"}

    def filing_step(watchlist, filings_config):
        calls.append(("filings", tuple(watchlist)))
        return {"downloaded_count": 0, "files": []}

    def brief_step(context):
        calls.append(("brief", context["market"]["market_status"]))
        return {"output_file": None}

    result = run_daily(
        cfg,
        market_step=market_step,
        filing_step=filing_step,
        brief_step=brief_step,
        dry_run=False,
    )

    assert [c[0] for c in calls] == ["market", "filings", "brief"]
    assert result["status"] == "success"


def test_run_daily_dry_run_does_not_execute_real_filing_step(tmp_path):
    cfg = replace(AssistantConfig(), filings=replace(AssistantConfig().filings, output_dir=tmp_path / "filings"))

    def market_step(config, run_id):
        return {"market_status": "green"}

    result = run_daily(
        cfg,
        market_step=market_step,
        dry_run=True,
        skip_brief=True,
    )

    assert result["filings"]["skipped"] is True
