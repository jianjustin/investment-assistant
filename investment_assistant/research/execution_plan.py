from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def create_execution_plan(*, ticker: str, direction: str, premise: str) -> dict[str, Any]:
    """Create an execution plan that must pass human review before action."""
    return {
        "artifact_type": "ExecutionPlan",
        "stage": "Plan",
        "source": "research.execution_plan",
        "generated_at": datetime.now(UTC).isoformat(),
        "ticker": ticker.strip().upper(),
        "direction": direction.strip().lower(),
        "premise": premise.strip(),
        "approval_status": "pending_review",
        "broker_action": None,
        "review_required": True,
        "review_notes": [],
        "risk_controls": [
            "人工确认前不得提交 broker order。",
            "确认 premise 仍成立后才能进入后续操作。",
        ],
        "allowed_review_actions": ["approve", "reject", "revise"],
    }
