from pathlib import Path

from investment_assistant.config import FilingsConfig
from investment_assistant.filings.service import download_configured_filings


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download_filings_batch(self, ticker, form_types, since_date, output_base):
        self.calls.append((ticker, form_types, since_date, output_base))
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
    assert downloader.calls[0][3] == tmp_path / "filings"
    assert result["downloaded_count"] == 1
    assert str(result["files"][0]).startswith(str(tmp_path / "filings"))
