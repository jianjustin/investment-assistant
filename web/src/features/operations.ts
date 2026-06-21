import type { AppState, Operation } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'
import { formatBool, riskLabel } from '../shared/format'

export function renderOperations(state: AppState, t: Translator): string {
  const operations = state.operations?.operations ?? []
  const table = renderTable<Operation>([
    { key: 'label', label: t('operation'), render: (operation) => `<div class="font-medium text-ink">${escapeHtml(operation.label)}</div><div class="text-xs text-muted">${escapeHtml(operation.id)}</div>` },
    { key: 'description', label: t('description'), render: (operation) => escapeHtml(operation.description) },
    { key: 'risk', label: t('risk'), render: (operation) => escapeHtml(riskLabel(operation, t)) },
    { key: 'confirmation', label: t('confirmation'), render: (operation) => escapeHtml(formatBool(operation.requires_confirmation, t)) },
    { key: 'enabled', label: t('status'), render: (operation) => renderStatusPill(operation.enabled ? t('enabled') : t('disabled'), operation.enabled ? 'good' : 'neutral') },
    { key: 'endpoint', label: t('endpoint'), render: (operation) => `<code class="text-xs text-slate-600">${escapeHtml(operation.endpoint)}</code>` },
  ], operations, t('noRows'))

  return `${renderPageHeader(t('operations'), t('operationsDesc'))}${renderPanel(t('manualOps'), t('quickActionsDesc'), table)}`
}
