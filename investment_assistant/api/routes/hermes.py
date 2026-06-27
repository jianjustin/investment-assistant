import investment_assistant.services.hermes as _hermes
from investment_assistant.api.http import ApiResponse
from investment_assistant.api.router import register
from investment_assistant.hermes import agents as hermes_agents


@register("GET", exact="/api/hermes")
def _overview(path, query, payload):
    return ApiResponse(hermes_agents.hermes_overview())


@register("GET", exact="/api/hermes/agents")
def _agents_list(path, query, payload):
    return ApiResponse({"agents": hermes_agents.list_agents()})


@register("GET", exact="/api/hermes/macro-analysis")
@register("GET", exact="/api/hermes/market-signals/interpretation")
def _macro_analysis(path, query, payload):
    return ApiResponse(_hermes.hermes_macro_analysis(query))


@register("POST", exact="/api/hermes/macro-analysis/run")
def _macro_run(path, query, payload):
    return ApiResponse(_hermes.submit_macro_llm(payload or {}))


@register("POST", exact="/api/hermes/decision-evidence/run")
def _decision_run(path, query, payload):
    return ApiResponse(_hermes.submit_decision_evidence(payload or {}))


@register("POST", exact="/api/hermes/agents")
def _agents_save(path, query, payload):
    return ApiResponse({"agent": hermes_agents.save_agent(payload or {})})
