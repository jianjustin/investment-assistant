from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from investment_assistant.api.http import parse_int
from investment_assistant.services import filings as _filings

router = APIRouter()


@router.get("/api/filings/records")
def records(ticker: str | None = None, form: str | None = None,
            from_: str | None = Query(default=None, alias="from"),
            to: str | None = None, limit: str | None = None):
    return _filings.filing_records(
        ticker=ticker, form=form, from_=from_, to=to,
        limit=parse_int(limit, default=50, minimum=1, maximum=500),
    )


@router.get("/api/filings/records/{filing_id}/download")
def download(filing_id: int):
    try:
        path = _filings.filing_download_path(filing_id)
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, filename=path.name)
