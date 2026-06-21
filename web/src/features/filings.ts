import type { AppState, FilingRow } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderMetric, renderPageHeader, renderPanel, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'
import { formatBool, formatBytes, formatTimestamp } from '../shared/format'

export function renderFilings(state: AppState, t: Translator): string {
  const summary = state.filings?.summary ?? state.status?.filings
  const rows = state.filings?.files ?? []
  const table = renderTable<FilingRow>([
    { key: 'name', label: t('name'), render: (row) => `<span class="font-medium text-ink">${escapeHtml(row.name ?? 'N/A')}</span>` },
    { key: 'path', label: t('path'), render: (row) => `<span title="${escapeHtml(row.path ?? '')}">${escapeHtml(row.path ?? 'N/A')}</span>` },
    { key: 'size', label: t('size'), align: 'right', render: (row) => escapeHtml(formatBytes(row.size)) },
    { key: 'modified_at', label: t('modifiedAt'), render: (row) => escapeHtml(formatTimestamp(row.modified_at, state.language)) },
  ], rows, t('noRows'))

  return `
    ${renderPageHeader(t('filings'), t('filingsDesc'))}
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
      ${renderMetric(t('files'), `${summary?.file_count ?? 0}`, 'file-text', summary?.path ?? 'N/A', summary?.exists ? 'bg-emerald-500' : 'bg-rose-500')}
      ${renderMetric(t('exists'), formatBool(summary?.exists, t), 'hard-drive', t('filingStorage'), summary?.exists ? 'bg-emerald-500' : 'bg-rose-500')}
      ${renderMetric(t('path'), summary?.path ?? 'N/A', 'braces', t('filingsDesc'), 'bg-slate-300')}
    </div>
    <div class="mt-4">${renderPanel(t('table'), t('filingsDesc'), table)}</div>
  `
}
