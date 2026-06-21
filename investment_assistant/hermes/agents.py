from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from investment_assistant.runtime_paths import CONFIG_DIR

AGENT_REGISTRY_PATH = CONFIG_DIR / "hermes-agents.json"
_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def hermes_capabilities() -> list[dict[str, Any]]:
    return [
        {
            "id": "market_signal_interpretation",
            "label": "市场信号解读",
            "description": "读取最近窗口的 market_signals，生成风险状态、摘要和建议动作。",
            "status": "ready",
            "endpoint": "/api/hermes/market-signals/interpretation?window=30",
            "inputs": ["market_signals"],
            "outputs": ["judgement", "summary", "metrics", "actions"],
        },
        {
            "id": "filing_digest",
            "label": "Filing 摘要",
            "description": "读取已下载 SEC 文件，生成公司事件摘要和待复核问题。",
            "status": "planned",
            "endpoint": None,
            "inputs": ["filings"],
            "outputs": ["summary", "questions", "risk_flags"],
        },
        {
            "id": "watchlist_research",
            "label": "Watchlist 研究编排",
            "description": "把市场环境、watchlist、技术信号和 filings 串成候选机会工作流。",
            "status": "planned",
            "endpoint": None,
            "inputs": ["watchlist", "market_signals", "filings"],
            "outputs": ["candidate_queue", "research_tasks"],
        },
    ]


def hermes_ideas() -> list[dict[str, str]]:
    return [
        {
            "title": "晨间市场总控 Agent",
            "description": "每天开盘前读取市场信号、watchlist 和持仓暴露，输出今日允许做什么、不允许做什么。",
            "next_step": "接入持仓/观察列表数据后，把它设为默认日跑 Agent。",
        },
        {
            "title": "Filing 事件雷达 Agent",
            "description": "当 8-K、10-Q、10-K 入库后自动提取收入、指引、风险因素变化和管理层措辞变化。",
            "next_step": "先从已下载 filings 文件做离线摘要，不直接触发交易动作。",
        },
        {
            "title": "反方挑战 Agent",
            "description": "对你准备买入或加仓的标的，强制列出市场环境、基本面、技术面和仓位四类反对理由。",
            "next_step": "把它做成手动操作入口，运行前要求填写 ticker 和投资假设。",
        },
        {
            "title": "复盘 Agent",
            "description": "按周读取信号、决策记录和结果，把预期与实际差异沉淀到复盘笔记。",
            "next_step": "等交易/观察动作有结构化记录后再接入。",
        },
    ]


def default_agents() -> list[dict[str, Any]]:
    now = "builtin"
    return [
        {
            "id": "market-signal-interpreter",
            "name": "市场信号解读 Agent",
            "role": "market_interpreter",
            "description": "把最近市场信号翻译成风险状态、摘要和建议动作。",
            "system_prompt": "基于 market_signals 输出谨慎、可追溯的市场环境判断，不给价格预测。",
            "data_sources": ["market_signals"],
            "tools": ["market_signal_interpretation"],
            "enabled": True,
            "custom": False,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "filing-digest-draft",
            "name": "Filing 摘要 Agent 草案",
            "role": "filing_digest",
            "description": "计划用于把 SEC 文件转成事件摘要和复核问题。",
            "system_prompt": "只基于 filings 原文摘要，不补充无来源判断。",
            "data_sources": ["filings"],
            "tools": ["filing_digest"],
            "enabled": False,
            "custom": False,
            "created_at": now,
            "updated_at": now,
        },
    ]


def hermes_overview() -> dict[str, Any]:
    return {
        "capabilities": hermes_capabilities(),
        "agents": list_agents(),
        "ideas": hermes_ideas(),
    }


def list_agents() -> list[dict[str, Any]]:
    custom_by_id = {agent["id"]: agent for agent in _read_custom_agents()}
    merged = []
    for agent in default_agents():
        merged.append({**agent, **custom_by_id.pop(agent["id"], {})})
    merged.extend(custom_by_id.values())
    return sorted(merged, key=lambda item: (not item.get("enabled", False), item.get("name", "")))


def save_agent(payload: dict[str, Any]) -> dict[str, Any]:
    agent_id = _clean_text(payload.get("id"))
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError("agent id must be 2-64 chars: lowercase letters, numbers, hyphen, underscore")
    name = _clean_text(payload.get("name"))
    if not name:
        raise ValueError("agent name is required")
    now = datetime.now(UTC).isoformat()
    existing = {agent["id"]: agent for agent in _read_custom_agents()}
    previous = existing.get(agent_id, {})
    agent = {
        "id": agent_id,
        "name": name,
        "role": _clean_text(payload.get("role")) or "custom",
        "description": _clean_text(payload.get("description")),
        "system_prompt": _clean_text(payload.get("system_prompt")),
        "data_sources": _string_list(payload.get("data_sources")),
        "tools": _string_list(payload.get("tools")),
        "enabled": bool(payload.get("enabled", True)),
        "custom": True,
        "created_at": previous.get("created_at", now),
        "updated_at": now,
    }
    existing[agent_id] = agent
    _write_custom_agents(list(existing.values()))
    return agent


def _read_custom_agents() -> list[dict[str, Any]]:
    if not AGENT_REGISTRY_PATH.exists():
        return []
    try:
        payload = json.loads(AGENT_REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    agents = payload.get("agents", []) if isinstance(payload, dict) else []
    return [agent for agent in agents if isinstance(agent, dict) and agent.get("id")]


def _write_custom_agents(agents: list[dict[str, Any]]) -> None:
    AGENT_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_REGISTRY_PATH.write_text(json.dumps({"agents": agents}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]
