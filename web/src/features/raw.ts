import type { AppState } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel } from '../shared/components'
import { escapeHtml } from '../shared/html'

export function renderRaw(state: AppState, t: Translator): string {
  const body = `<pre class="max-h-[640px] overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel p-3 text-xs leading-5 text-slate-700">${escapeHtml(JSON.stringify(state.raw ?? state.status ?? {}, null, 2))}</pre>`
  return `${renderPageHeader(t('raw'), t('rawDesc'))}${renderPanel(t('rawSnapshot'), t('rawDesc'), body)}`
}
