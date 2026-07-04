from typing import Any

from fastapi import APIRouter, Body, HTTPException

from investment_assistant.services import settings

router = APIRouter()


@router.get("/api/settings/notify")
def get_notify():
    return settings.read_notify_view()


@router.patch("/api/settings/notify")
def patch_notify(payload: dict[str, Any] = Body(default_factory=dict)):
    return settings.update_notify(payload)


@router.post("/api/settings/notify/test")
def test_notify(payload: dict[str, Any] = Body(default_factory=dict)):
    channel = payload.get("channel")
    if not channel:
        raise HTTPException(status_code=400, detail="channel required")
    return settings.test_notify_channel(channel, url=payload.get("url"))


@router.get("/api/settings/env")
def env_status():
    return settings.read_env_status()
