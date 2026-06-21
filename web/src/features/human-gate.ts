import type { AppState, HumanGatePlan } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'

const pendingPlans: HumanGatePlan[] = [
  {
    ticker: 'TSLA',
    direction: 'watch',
    premise: 'macro must remain offense; strategy evidence must improve before any plan can advance.',
    approval_status: 'pending_review',
    broker_action: null,
  },
]

export function renderHumanGate(state: AppState, t: Translator): string {
  return `
    ${renderPageHeader(t('humanGate'), t('humanGateDesc'))}
    <div class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="metric-panel"><div class="label">${escapeHtml(t('pendingReview'))}</div><div class="value mt-2">${pendingPlans.length}</div><div class="mt-2 text-sm text-muted">ExecutionPlan</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('brokerAction'))}</div><div class="value mt-2">0</div><div class="mt-2 text-sm text-muted">${escapeHtml(t('humanGateNoBrokerAction'))}</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('status'))}</div><div class="mt-3">${renderStatusPill(t('pendingReview'), 'warn')}</div><div class="mt-2 text-sm text-muted">${escapeHtml(state.language === 'zh' ? '人工确认前不得执行' : 'No action before review')}</div></div>
    </div>
    ${renderPanel(t('humanGatePendingPlans'), t('humanGatePendingPlansDesc'), renderPendingPlanTable(pendingPlans, t))}
  `
}

function renderPendingPlanTable(rows: HumanGatePlan[], t: Translator): string {
  return renderTable<HumanGatePlan>([
    { key: 'ticker', label: t('ticker'), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span>` },
    { key: 'direction', label: t('direction'), render: (row) => escapeHtml(row.direction) },
    { key: 'premise', label: t('premise'), render: (row) => `<span class="text-slate-700">${escapeHtml(row.premise)}</span>` },
    { key: 'approval_status', label: t('approvalStatus'), render: (row) => renderStatusPill(row.approval_status, 'warn') },
    { key: 'actions', label: t('manualReviewActions'), render: () => renderActionPlaceholders(t) },
  ], rows, t('noRows'))
}

function renderActionPlaceholders(t: Translator): string {
  return `
    <div class="flex flex-wrap gap-2">
      ${renderPlaceholderButton('approve', t('approve'))}
      ${renderPlaceholderButton('reject', t('reject'))}
      ${renderPlaceholderButton('revise', t('revise'))}
    </div>
  `
}

function renderPlaceholderButton(action: 'approve' | 'reject' | 'revise', label: string): string {
  return `<button type="button" data-human-gate-action="${action}" class="rounded-md border border-line bg-white px-2.5 py-1 text-xs font-semibold text-muted" disabled>${escapeHtml(label)}</button>`
}
