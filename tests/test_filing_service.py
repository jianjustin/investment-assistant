from datetime import date, timedelta
from pathlib import Path

from investment_assistant.config import FilingsConfig
from investment_assistant.filings.service import download_configured_filings


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download_filings_batch(self, ticker, form_types, start_date, end_date, output_base):
        self.calls.append((ticker, form_types, start_date, end_date, output_base))
        path = Path(output_base) / ticker / form_types[0] / "000-test.htm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<html>ok</html>")
        return [path]


def test_download_configured_filings_uses_runtime_output_dir(tmp_path):
    cfg = FilingsConfig(forms=["10-Q", "10-K"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    result = download_configured_filings(["NVDA"], cfg, downloader=downloader)

    assert downloader.calls[0][0] == "NVDA"
    assert downloader.calls[0][1] == ["10-Q", "10-K"]
    assert downloader.calls[0][4] == tmp_path / "filings"
    assert result["downloaded_count"] == 1
    assert str(result["files"][0]).startswith(str(tmp_path / "filings"))


def test_download_defaults_to_t_minus_1(tmp_path):
    cfg = FilingsConfig(forms=["10-Q"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    download_configured_filings(["NVDA"], cfg, downloader=downloader)

    yesterday = date.today() - timedelta(days=1)
    assert downloader.calls[0][2] == yesterday
    assert downloader.calls[0][3] == yesterday


def test_download_passes_explicit_date_range(tmp_path):
    cfg = FilingsConfig(forms=["10-Q"], lookback_years=1, output_dir=tmp_path / "filings")
    downloader = FakeDownloader()

    download_configured_filings(
        ["NVDA"], cfg, downloader=downloader,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 30),
    )

    assert downloader.calls[0][2] == date(2026, 6, 1)
    assert downloader.calls[0][3] == date(2026, 6, 30)
