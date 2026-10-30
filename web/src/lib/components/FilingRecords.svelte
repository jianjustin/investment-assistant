<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import { fmtTime } from '../format'

  // Extracted unchanged from the legacy Data page's filings tab.
  let filings = $state<any[]>([])
  let filingTickers = $state<string[]>([])
  let fTicker = $state('')
  let fForm = $state('')
  let fFrom = $state('')
  let fTo = $state('')

  async function loadFilings() {
    const r = await api.getFilingRecords({
      ticker: fTicker || undefined,
      form: fForm || undefined,
      from: fFrom || undefined,
      to: fTo || undefined,
    })
    filings = r.records
    filingTickers = r.tickers
  }

  onMount(loadFilings)
</script>

<div class="space-y-3">
  <div class="flex flex-wrap items-center gap-2">
    <select aria-label="按标的筛选" bind:value={fTicker} onchange={loadFilings} class="text-sm border border-border rounded-sm px-2 py-1 bg-card">
      <option value="">全部标的</option>
      {#each filingTickers as t}<option value={t}>{t}</option>{/each}
    </select>
    <select aria-label="按类型筛选" bind:value={fForm} onchange={loadFilings} class="text-sm border border-border rounded-sm px-2 py-1 bg-card">
      <option value="">全部类型</option><option value="10-Q">10-Q</option><option value="10-K">10-K</option>
    </select>
    <input aria-label="开始日期" type="date" bind:value={fFrom} onchange={loadFilings} class="text-sm border border-border rounded-sm px-2 py-1 bg-card" />
    <span class="text-xs text-muted-foreground">至</span>
    <input aria-label="结束日期" type="date" bind:value={fTo} onchange={loadFilings} class="text-sm border border-border rounded-sm px-2 py-1 bg-card" />
  </div>
  <div class="bg-card rounded-lg shadow-1 overflow-hidden">
    <table class="w-full text-sm">
      <thead>
        <tr class="text-muted-foreground text-left">
          <th class="px-3 py-2">标的</th><th>类型</th><th>财报日期</th><th>下载时间</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each filings as f}
          <tr class="border-t border-border">
            <td class="px-3 py-2 font-medium">{f.ticker}</td>
            <td>{f.form}</td>
            <td>{f.filing_date}</td>
            <td>{fmtTime(f.downloaded_at)}</td>
            <td class="text-right pr-3">
              <a class="text-primary text-xs" href={api.filingDownloadUrl(f.id)} download>下载 htm</a>
            </td>
          </tr>
        {:else}
          <tr><td colspan="5" class="px-3 py-4 text-muted-foreground text-sm">暂无财报记录（可在「工具 · 任务中心」对 filings 按日期回补）</td></tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>
