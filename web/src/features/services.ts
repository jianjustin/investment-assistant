import type { AppState } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderServiceRow } from '../shared/components'
import { serviceDot, serviceLabel } from '../shared/format'
import { compactLines, escapeHtml } from '../shared/html'

export function renderServices(state: AppState, t: Translator): string {
  const services = state.services ?? state.status?.system
  const body = `
    <div class="space-y-3">
      ${renderServiceRow(t('dashboard'), serviceLabel(services?.dashboard_service, t), serviceDot(services?.dashboard_service))}
      ${renderServiceRow(t('postgres'), serviceLabel(services?.postgres_service, t), serviceDot(services?.postgres_service))}
      ${renderServiceRow(t('dailyTimer'), serviceLabel(services?.timer, t), serviceDot(services?.timer))}
    </div>
    <div class="mt-4">
      <div class="label">${escapeHtml(t('timerOutput'))}</div>
      <pre class="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-slate-950 p-3 text-xs leading-5 text-slate-100">${escapeHtml(compactLines(services?.timer?.output, t('noTimerOutput')))}</pre>
    </div>
  `
  return `${renderPageHeader(t('services'), t('servicesDesc'))}${renderPanel(t('serviceRuntime'), t('servicesDesc'), body)}`
}
