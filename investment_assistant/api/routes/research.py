from investment_assistant.api.http import ApiResponse, first, parse_optional_date
from investment_assistant.api.router import register
from investment_assistant.services import research


@register("GET", exact="/api/research/event-study/kinds")
def _kinds(path, query, payload):
    return ApiResponse(research.available_kinds())


@register("GET", exact="/api/research/event-study")
def _event_study(path, query, payload):
    kind = first(query, "kind")
    if not kind:
        return ApiResponse({"error": "kind is required"}, status=400)
    since = parse_optional_date(first(query, "since"))
    asof = parse_optional_date(first(query, "asof"))
    return ApiResponse(research.event_study_view(kind, since=since, asof=asof))
