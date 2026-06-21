import type { AppState, HermesAgent, HermesCapability, HermesIdea, RouteId } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderMetric, renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'

export function renderHermes(state: AppState, t: Translator, route: RouteId = 'hermes-overview'): string {
  if (route === 'hermes-agents') return renderAgentsPage(state, t)
  if (route === 'hermes-ideas') return renderIdeasPage(state, t)
  return renderOverviewPage(state, t)
}

function renderOverviewPage(state: AppState, t: Translator): string {
  const payload = state.hermes
  const capabilities = payload?.capabilities ?? []
  const agents = payload?.agents ?? []
  const ready = capabilities.filter((capability) => capability.status === 'ready').length
  const enabledAgents = agents.filter((agent) => agent.enabled).length
  return `
    ${renderPageHeader(t('hermesOverview'), t('hermesOverviewDesc'))}
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
      ${renderMetric(t('hermesCapabilities'), `${capabilities.length}`, 'activity', `${ready} ${t('ready')}`, 'bg-teal-500')}
      ${renderMetric(t('hermesAgents'), `${agents.length}`, 'database', `${enabledAgents} ${t('enabled')}`, 'bg-indigo-500')}
      ${renderMetric(t('hermesIdeas'), `${payload?.ideas.length ?? 0}`, 'braces', t('hermesIdeasDesc'), 'bg-amber-500')}
    </div>
    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      ${renderPanel(t('hermesCapabilities'), t('hermesCapabilitiesDesc'), renderCapabilityTable(capabilities, t))}
      ${renderPanel(t('hermesHowToUse'), t('hermesHowToUseDesc'), renderHermesUseCases(t))}
    </div>
  `
}

function renderAgentsPage(state: AppState, t: Translator): string {
  const agents = state.hermes?.agents ?? []
  return `
    ${renderPageHeader(t('hermesAgents'), t('hermesAgentsDesc'))}
    <div class="grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      ${renderPanel(t('hermesAgentRegistry'), t('hermesAgentRegistryDesc'), renderAgentTable(agents, t))}
      ${renderPanel(t('hermesCustomAgent'), t('hermesCustomAgentDesc'), renderAgentForm(state, t))}
    </div>
  `
}

function renderIdeasPage(state: AppState, t: Translator): string {
  const ideas = state.hermes?.ideas ?? []
  return `
    ${renderPageHeader(t('hermesIdeas'), t('hermesIdeasDesc'))}
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      ${ideas.map((idea) => renderIdea(idea, t)).join('') || `<div class="section-panel text-sm text-muted">${escapeHtml(t('noRows'))}</div>`}
    </div>
  `
}

function renderCapabilityTable(capabilities: HermesCapability[], t: Translator): string {
  return renderTable<HermesCapability>([
    { key: 'label', label: t('name'), render: (capability) => `<div class="font-medium text-ink">${escapeHtml(capability.label)}</div><div class="text-xs text-muted">${escapeHtml(capability.id)}</div>` },
    { key: 'status', label: t('status'), render: (capability) => renderStatusPill(capability.status === 'ready' ? t('ready') : t('planned'), capability.status === 'ready' ? 'good' : 'neutral') },
    { key: 'inputs', label: t('inputs'), render: (capability) => escapeHtml(capability.inputs.join(', ')) },
    { key: 'outputs', label: t('outputs'), render: (capability) => escapeHtml(capability.outputs.join(', ')) },
  ], capabilities, t('noRows'))
}

function renderAgentTable(agents: HermesAgent[], t: Translator): string {
  return renderTable<HermesAgent>([
    { key: 'name', label: t('name'), render: (agent) => `<div class="font-medium text-ink">${escapeHtml(agent.name)}</div><div class="text-xs text-muted">${escapeHtml(agent.id)}</div>` },
    { key: 'role', label: t('role'), render: (agent) => escapeHtml(agent.role) },
    { key: 'tools', label: t('tools'), render: (agent) => escapeHtml(agent.tools.join(', ') || 'N/A') },
    { key: 'enabled', label: t('status'), render: (agent) => renderStatusPill(agent.enabled ? t('enabled') : t('disabled'), agent.enabled ? 'good' : 'neutral') },
    { key: 'custom', label: t('type'), render: (agent) => escapeHtml(agent.custom ? t('custom') : t('builtin')) },
  ], agents, t('noRows'))
}

function renderAgentForm(state: AppState, t: Translator): string {
  const result = state.hermesAgentResult
  return `
    <form id="hermesAgentForm" class="space-y-3">
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('agentId'))}<input name="id" value="risk-reviewer" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('name'))}<input name="name" value="风险复核 Agent" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('role'))}<input name="role" value="risk_reviewer" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('description'))}<textarea name="description" rows="2" class="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm">复核市场信号、watchlist 和持仓风险。</textarea></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('systemPrompt'))}<textarea name="system_prompt" rows="4" class="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm">只输出风险检查清单；不得给出价格预测；所有判断必须说明来源。</textarea></label>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="block text-sm font-medium text-ink">${escapeHtml(t('dataSources'))}<input name="data_sources" value="market_signals,watchlist" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
        <label class="block text-sm font-medium text-ink">${escapeHtml(t('tools'))}<input name="tools" value="market_signal_interpretation" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      </div>
      <label class="inline-flex items-center gap-2 text-sm text-ink"><input name="enabled" type="checkbox" checked />${escapeHtml(t('enabled'))}</label>
      <button type="submit" class="inline-flex h-10 w-full items-center justify-center rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.hermesAgentSaving ? 'disabled' : ''}>${escapeHtml(state.hermesAgentSaving ? t('saving') : t('saveAgent'))}</button>
      ${result ? `<div class="rounded-md border ${result.error ? 'border-rose-200 bg-rose-50 text-rose-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'} px-3 py-2 text-sm">${escapeHtml(result.error ? result.error : t('agentSaved'))}</div>` : ''}
    </form>
  `
}

function renderHermesUseCases(t: Translator): string {
  const items = [t('hermesUseCaseMarket'), t('hermesUseCaseFiling'), t('hermesUseCaseChallenge'), t('hermesUseCaseReview')]
  return `<div class="space-y-2">${items.map((item) => `<div class="rounded-md border border-line bg-panel px-3 py-2 text-sm text-slate-700">${escapeHtml(item)}</div>`).join('')}</div>`
}

function renderIdea(idea: HermesIdea, t: Translator): string {
  return `
    <section class="section-panel">
      <div class="text-base font-semibold text-ink">${escapeHtml(idea.title)}</div>
      <p class="mt-2 text-sm text-muted">${escapeHtml(idea.description)}</p>
      <div class="mt-4 rounded-md border border-line bg-panel px-3 py-2 text-sm text-slate-700"><span class="font-semibold text-ink">${escapeHtml(t('nextStep'))}: </span>${escapeHtml(idea.next_step)}</div>
    </section>
  `
}
