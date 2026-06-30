from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.services import settings


@register("GET", exact="/api/settings/notify")
def _get_notify(path, query, payload):
    return ApiResponse(settings.read_notify_view())


@register("PATCH", exact="/api/settings/notify")
def _patch_notify(path, query, payload):
    return ApiResponse(settings.update_notify(payload or {}))


@register("POST", exact="/api/settings/notify/test")
def _test_notify(path, query, payload):
    body = payload or {}
    channel = body.get("channel")
    if not channel:
        return ApiResponse({"error": "channel required"}, status=400)
    return ApiResponse(settings.test_notify_channel(channel, url=body.get("url")))


@register("GET", exact="/api/settings/env")
def _get_env(path, query, payload):
    return ApiResponse(settings.read_env_status())
