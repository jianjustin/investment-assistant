from fastapi import APIRouter

import investment_assistant.services.status as _status
from investment_assistant.services.health import health_report

router = APIRouter()


@router.get("/api/status")
@router.get("/api/raw/status")
def status_route():
    return _status.status_payload()


@router.get("/api/health")
def health():
    return health_report()


@router.get("/api/services")
def services():
    return _status.system_status()


@router.get("/api/operations")
def operations():
    return {"operations": _status.operation_registry()}
