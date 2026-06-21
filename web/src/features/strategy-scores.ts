import type { AppState, RouteId, StrategyScore } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'

export function renderStrategyScores(state: AppState, t: Translator, route: RouteId): string {
  const rows = state.strategyScores?.rows ?? []
  const averageScore = rows.length > 0 ? Math.round(rows.reduce((sum, row) => sum + Number(row.score ?? 0), 0) / rows.length) : 0
  return `
    ${renderPageHeader(t('strategyModule'), t('strategyModuleDesc'))}
    ${renderStrategyRunPanel(state, t)}
    <div class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="metric-panel"><div class="label">${escapeHtml(t('sampleSize'))}</div><div class="value mt-2">${rows.length}</div><div class="mt-2 text-sm text-muted">strategy_scores</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('score'))}</div><div class="value mt-2">${averageScore}</div><div class="mt-2 text-sm text-muted">0 - 100</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('source'))}</div><div class="value mt-2">${escapeHtml(rows[0]?.strategy ?? 'N/A')}</div><div class="mt-2 text-sm text-muted">Python strategy scoring</div></div>
    </div>
    ${route === 'strategy-runs' ? renderPanel(t('strategyRuns'), t('strategyRunsDesc'), `<div class="text-sm text-muted">${escapeHtml(t('strategyRunHistoryPlanned'))}</div>`, 'mb-4') : ''}
    ${renderPanel(t('strategyScoresCurrent'), t('strategyScoresCurrentDesc'), renderStrategyScoreTable(rows, t))}
  `
}


function renderStrategyRunPanel(state: AppState, t: Translator): string {
  const result = state.strategyScoreRunResult
  const failures = result?.failures?.length ?? 0
  const status = state.strategyScoreRunInFlight
    ? `<div class="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"><span class="inline-flex items-center gap-2"><i data-lucide="refresh-cw" class="h-4 w-4 animate-spin" aria-hidden="true"></i>${escapeHtml(t('runningStrategyScores'))}</span></div>`
    : result?.error
      ? `<div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">${escapeHtml(result.error)}</div>`
      : result?.run_id
        ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">${escapeHtml(t('strategyScoreRunComplete'))}: ${result.count ?? 0} · ${escapeHtml(t('fetchFailure'))}: ${failures}</div>`
        : ''
  return `
    <div class="mb-4 section-panel">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div class="label">${escapeHtml(t('strategyManualRun'))}</div>
          <p class="mt-1 text-sm text-muted">${escapeHtml(t('strategyManualRunDesc'))}</p>
        </div>
        <button id="strategyScoreRunButton" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.strategyScoreRunInFlight ? 'disabled' : ''}>
          <i data-lucide="refresh-cw" class="h-4 w-4 ${state.strategyScoreRunInFlight ? 'animate-spin' : ''}" aria-hidden="true"></i>${escapeHtml(state.strategyScoreRunInFlight ? t('runningStrategyScores') : t('runStrategyScores'))}
        </button>
      </div>
      ${status ? `<div class="mt-3">${status}</div>` : ''}
    </div>
  `
}

function renderStrategyScoreTable(rows: StrategyScore[], t: Translator): string {
  return renderTable<StrategyScore>([
    { key: 'ticker', label: t('ticker'), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span><div class="mt-1 text-xs text-muted">${escapeHtml(row.score_date ?? 'N/A')}</div>` },
    { key: 'strategy', label: t('strategyScores'), render: (row) => `<span class="font-medium text-ink">${escapeHtml(row.strategy)}</span>` },
    { key: 'score', label: t('score'), align: 'right', render: (row) => renderStatusPill(String(row.score), scoreTone(row.score)) },
    { key: 'evidence', label: t('strategyEvidence'), render: (row) => renderTags(row.evidence ?? []) },
    { key: 'limits', label: t('strategyLimits'), render: (row) => renderTags(row.limits ?? []) },
    { key: 'run_id', label: 'Run ID', render: (row) => `<span class="text-xs text-muted">${escapeHtml(row.run_id ?? '-')}</span>` },
  ], rows, t('noRows'))
}

function renderTags(items: string[]): string {
  if (items.length === 0) return '<span class="text-muted">-</span>'
  return `<div class="flex flex-wrap gap-1">${items.map((item) => `<span class="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700">${escapeHtml(item)}</span>`).join('')}</div>`
}

function scoreTone(score: number): 'neutral' | 'good' | 'warn' | 'bad' {
  if (score >= 75) return 'good'
  if (score >= 50) return 'warn'
  if (score > 0) return 'neutral'
  return 'bad'
}
