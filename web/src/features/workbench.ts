import type { AppState } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderMetric, renderPanel, renderStatusPill } from '../shared/components'
import { escapeHtml } from '../shared/html'
import { marketDot, marketLabel, serviceDot, serviceLabel } from '../shared/format'

export function renderWorkbench(state: AppState, t: Translator): string {
  const dbOk = state.status?.database?.ok === true
  const signal = state.latestSignal ?? state.status?.database?.latest_market_signal
  const filingCount = state.filings?.summary?.file_count ?? state.status?.filings?.file_count ?? 0
  const filingExists = state.filings?.summary?.exists ?? state.status?.filings?.exists
  const dashboardService = state.services?.dashboard_service ?? state.status?.system?.dashboard_service
  const postgresService = state.services?.postgres_service ?? state.status?.system?.postgres_service
  const attentionItems = [
    dbOk ? null : t('database'),
    filingExists ? null : t('filingStorage'),
    dashboardService?.ok ? null : t('serviceRuntime'),
    postgresService?.ok ? null : t('postgres'),
  ].filter(Boolean)

  const attentionBody = attentionItems.length === 0
    ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">${escapeHtml(t('noAttention'))}</div>`
    : `<div class="space-y-2">${attentionItems.map((item) => `<div class="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">${escapeHtml(item)}</div>`).join('')}</div>`

  const operations = state.operations?.operations ?? []
  const shortcuts = operations.slice(0, 3).map((operation) => `
    <div class="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
      <div class="min-w-0">
        <div class="truncate text-sm font-medium text-ink">${escapeHtml(operation.label)}</div>
        <div class="truncate text-xs text-muted">${escapeHtml(operation.description)}</div>
      </div>
      ${renderStatusPill(operation.enabled ? t('enabled') : t('disabled'), operation.enabled ? 'good' : 'neutral')}
    </div>
  `).join('')

  return `
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      ${renderMetric(t('database'), dbOk ? t('connected') : t('error'), 'database', 'market_signals', dbOk ? 'bg-emerald-500' : 'bg-rose-500')}
      ${renderMetric(t('market'), marketLabel(signal, t), 'activity', signal?.signal_date ?? 'N/A', marketDot(signal))}
      ${renderMetric(t('filingStorage'), `${filingCount} ${t('files')}`, 'file-text', state.filings?.summary?.path ?? 'N/A', filingExists ? 'bg-emerald-500' : 'bg-rose-500')}
      ${renderMetric(t('serviceRuntime'), serviceLabel(dashboardService, t), 'server', `${t('postgres')}: ${serviceLabel(postgresService, t)}`, serviceDot(dashboardService))}
    </div>
    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[0.9fr_1.1fr]">
      ${renderPanel(t('attention'), t('attentionDesc'), attentionBody)}
      ${renderPanel(t('quickActions'), t('quickActionsDesc'), shortcuts || `<div class="text-sm text-muted">${escapeHtml(t('noRows'))}</div>`)}
    </div>
  `
}
