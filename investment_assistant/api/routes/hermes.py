from typing import Any

from fastapi import APIRouter, Body, Depends

import investment_assistant.services.hermes as _hermes
from investment_assistant.api.params import query_lists
from investment_assistant.hermes import agents as hermes_agents

router = APIRouter()


@router.get("/api/hermes")
def overview():
    return hermes_agents.hermes_overview()


@router.get("/api/hermes/agents")
def agents_list():
    return {"agents": hermes_agents.list_agents()}


@router.get("/api/hermes/macro-analysis")
@router.get("/api/hermes/market-signals/interpretation")
def macro_analysis(query: dict[str, list[str]] = Depends(query_lists)):
    return _hermes.hermes_macro_analysis(query)


@router.post("/api/hermes/macro-analysis/run")
def macro_run(payload: dict[str, Any] = Body(default_factory=dict)):
    return _hermes.submit_macro_llm(payload)


@router.post("/api/hermes/decision-evidence/run")
def decision_run(payload: dict[str, Any] = Body(default_factory=dict)):
    return _hermes.submit_decision_evidence(payload)


@router.post("/api/hermes/agents")
def agents_save(payload: dict[str, Any] = Body(default_factory=dict)):
    return {"agent": hermes_agents.save_agent(payload)}
