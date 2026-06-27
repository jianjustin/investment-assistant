import investment_assistant.services.status as _status
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.dashboard.health import health_report


@register("GET", exact="/api/status")
@register("GET", exact="/api/raw/status")
def _status_route(path, query, payload):
    return ApiResponse(_status.status_payload())


@register("GET", exact="/api/health")
def _health(path, query, payload):
    return ApiResponse(health_report())


@register("GET", exact="/api/services")
def _services(path, query, payload):
    return ApiResponse(_status.system_status())


@register("GET", exact="/api/filings")
def _filings(path, query, payload):
    return ApiResponse({"summary": _status.filing_status(), "files": _status.filing_rows()})


@register("GET", exact="/api/operations")
def _operations(path, query, payload):
    return ApiResponse({"operations": _status.operation_registry()})
