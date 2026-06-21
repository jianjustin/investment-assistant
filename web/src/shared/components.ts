import { escapeHtml } from './html'

export type TableColumn<T> = {
  key: string
  label: string
  header?: string
  align?: 'left' | 'right' | 'center'
  render: (row: T) => string
}

export function renderPageHeader(title: string, description: string): string {
  return `
    <div class="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 class="text-xl font-semibold text-ink">${escapeHtml(title)}</h2>
        <p class="mt-1 text-sm text-muted">${escapeHtml(description)}</p>
      </div>
    </div>
  `
}

export function renderPanel(title: string, description: string, body: string, extraClass = ''): string {
  return `
    <section class="section-panel ${extraClass}">
      <div class="label">${escapeHtml(title)}</div>
      ${description ? `<p class="mt-1 text-sm text-muted">${escapeHtml(description)}</p>` : ''}
      <div class="mt-4">${body}</div>
    </section>
  `
}

export function renderMetric(title: string, value: string, icon: string, detail = '', dotClass = 'bg-slate-300'): string {
  return `
    <section class="metric-panel min-h-[112px]">
      <div class="flex items-center justify-between gap-3">
        <div class="label">${escapeHtml(title)}</div>
        <i data-lucide="${icon}" class="h-4 w-4 text-muted" aria-hidden="true"></i>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <span class="status-dot ${dotClass}" aria-hidden="true"></span>
        <div class="value truncate">${escapeHtml(value)}</div>
      </div>
      <div class="mt-2 min-h-5 truncate text-sm text-muted">${escapeHtml(detail)}</div>
    </section>
  `
}

export function renderStatusPill(label: string, tone: 'neutral' | 'good' | 'warn' | 'bad' = 'neutral'): string {
  const classes = {
    neutral: 'border-slate-200 bg-slate-100 text-slate-700',
    good: 'border-emerald-200 bg-emerald-100 text-emerald-800',
    warn: 'border-amber-200 bg-amber-100 text-amber-800',
    bad: 'border-rose-200 bg-rose-100 text-rose-800',
  }[tone]
  return `<span class="inline-flex rounded-md border px-2.5 py-1 text-xs font-semibold ${classes}">${escapeHtml(label)}</span>`
}

export function renderTable<T>(columns: TableColumn<T>[], rows: T[], emptyText: string): string {
  if (rows.length === 0) {
    return `<div class="rounded-md border border-line bg-panel px-3 py-6 text-center text-sm text-muted">${escapeHtml(emptyText)}</div>`
  }
  return `
    <div class="overflow-x-auto rounded-md border border-line">
      <table class="min-w-full divide-y divide-line text-sm">
        <thead class="bg-panel text-left text-xs font-semibold uppercase tracking-normal text-muted">
          <tr>
            ${columns.map((column) => `<th class="px-3 py-2 ${column.align === 'right' ? 'text-right' : column.align === 'center' ? 'text-center' : 'text-left'}">${column.header ?? escapeHtml(column.label)}</th>`).join('')}
          </tr>
        </thead>
        <tbody class="divide-y divide-line bg-white text-slate-700">
          ${rows.map((row) => `
            <tr class="hover:bg-slate-50">
              ${columns.map((column) => `<td class="max-w-[320px] px-3 py-2 ${column.align === 'right' ? 'text-right' : column.align === 'center' ? 'text-center' : 'text-left'}">${column.render(row)}</td>`).join('')}
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `
}

export function renderServiceRow(name: string, value: string, dotClass: string): string {
  return `
    <div class="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
      <div class="flex min-w-0 items-center gap-2">
        <span class="status-dot ${dotClass}" aria-hidden="true"></span>
        <span class="truncate text-sm font-medium text-ink">${escapeHtml(name)}</span>
      </div>
      <span class="truncate text-sm text-muted">${escapeHtml(value)}</span>
    </div>
  `
}
