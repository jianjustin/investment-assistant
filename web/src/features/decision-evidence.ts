import type { AppState, DecisionEvidencePayload } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill } from '../shared/components'
import { escapeHtml } from '../shared/html'

export function renderDecisionEvidence(state: AppState, t: Translator): string {
  const evidence = state.decisionEvidenceResult?.decision_evidence ?? state.decisionEvidence
  return `
    ${renderPageHeader(t('decisionEvidence'), t('decisionEvidenceDesc'))}
    ${renderRunPanel(state, t)}
    ${evidence ? renderEvidenceSections(evidence, t) : renderPanel(t('decisionEvidence'), t('decisionEvidenceManualRunDesc'), `<div class="text-sm text-muted">${escapeHtml(t('noRows'))}</div>`)}
  `
}

function renderRunPanel(state: AppState, t: Translator): string {
  const result = state.decisionEvidenceResult
  const status = state.decisionEvidenceInFlight
    ? `<div class="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"><span class="inline-flex items-center gap-2"><i data-lucide="refresh-cw" class="h-4 w-4 animate-spin" aria-hidden="true"></i>${escapeHtml(t('runningDecisionEvidence'))}</span></div>`
    : result?.error
      ? `<div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">${escapeHtml(result.error)}</div>`
      : result?.run_id
        ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">${escapeHtml(t('decisionEvidenceComplete'))}: ${escapeHtml(result.run_id)}</div>`
        : ''
  return `
    <div class="mb-4 section-panel">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div class="label">${escapeHtml(t('decisionEvidenceManualRun'))}</div>
          <p class="mt-1 text-sm text-muted">${escapeHtml(t('decisionEvidenceManualRunDesc'))}</p>
        </div>
        <button id="decisionEvidenceButton" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.decisionEvidenceInFlight ? 'disabled' : ''}>
          <i data-lucide="refresh-cw" class="h-4 w-4 ${state.decisionEvidenceInFlight ? 'animate-spin' : ''}" aria-hidden="true"></i>${escapeHtml(state.decisionEvidenceInFlight ? t('runningDecisionEvidence') : t('generateDecisionEvidence'))}
        </button>
      </div>
      ${status ? `<div class="mt-3">${status}</div>` : ''}
    </div>
  `
}

function renderEvidenceSections(evidence: DecisionEvidencePayload, t: Translator): string {
  const llmTone = evidence.llm?.used ? 'good' : evidence.llm?.mode === 'fallback' ? 'warn' : 'neutral'
  return `
    <div class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="metric-panel"><div class="label">${escapeHtml(t('macroLlmStatus'))}</div><div class="mt-3">${renderStatusPill(evidence.llm?.used ? t('macroLlmUsed') : evidence.llm?.mode === 'fallback' ? t('macroLlmFallback') : t('macroLlmNotRun'), llmTone)}</div><div class="mt-2 text-sm text-muted">${escapeHtml(evidence.llm?.model ?? 'N/A')}</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('tickerFocus'))}</div><div class="value mt-2">${evidence.ticker_focus?.length ?? 0}</div><div class="mt-2 text-sm text-muted">watchlist trends</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('strategyEvidenceSection'))}</div><div class="value mt-2">${evidence.strategy_evidence?.length ?? 0}</div><div class="mt-2 text-sm text-muted">strategy_scores</div></div>
    </div>
    ${renderPanel(t('summary'), '', `<p class="text-sm leading-6 text-slate-700">${escapeHtml(evidence.summary ?? '')}</p>`, 'mb-4')}
    <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
      ${renderPanel(t('marketContext'), '', renderKeyValues(evidence.market_context ?? {}))}
      ${renderPanel(t('tickerFocus'), '', renderObjectList(evidence.ticker_focus ?? []))}
      ${renderPanel(t('strategyEvidenceSection'), '', renderObjectList(evidence.strategy_evidence ?? []))}
      ${renderPanel(t('riskQuestions'), '', renderList(evidence.risk_questions ?? []))}
      ${renderPanel(t('hermesActions'), '', renderList(evidence.next_actions ?? []), 'xl:col-span-2')}
    </div>
  `
}

function renderKeyValues(value: Record<string, unknown>): string {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined && item !== null && item !== '')
  if (!entries.length) return '<div class="text-sm text-muted">N/A</div>'
  return `<div class="space-y-2">${entries.map(([key, item]) => `<div class="flex gap-3 rounded-md border border-line bg-panel px-3 py-2 text-sm"><span class="w-32 shrink-0 font-medium text-ink">${escapeHtml(key)}</span><span class="min-w-0 text-slate-700">${escapeHtml(formatValue(item))}</span></div>`).join('')}</div>`
}

function renderObjectList(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return '<div class="text-sm text-muted">N/A</div>'
  return `<div class="space-y-2">${rows.slice(0, 12).map((row) => `<div class="rounded-md border border-line bg-panel px-3 py-2 text-sm text-slate-700">${Object.entries(row).filter(([, value]) => value !== undefined && value !== null && value !== '').map(([key, value]) => `<div><span class="font-medium text-ink">${escapeHtml(key)}:</span> ${escapeHtml(formatValue(value))}</div>`).join('')}</div>`).join('')}</div>`
}

function renderList(items: string[]): string {
  if (!items.length) return '<div class="text-sm text-muted">N/A</div>'
  return `<ul class="space-y-2">${items.map((item) => `<li class="rounded-md border border-line bg-panel px-3 py-2 text-sm text-slate-700">${escapeHtml(item)}</li>`).join('')}</ul>`
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value ?? '')
}
