<script lang="ts">
  import { onMount } from 'svelte'
  import { Button } from '$lib/ui/button/index'
  import DataTable from '$lib/ui/data-table/DataTable.svelte'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import { Input } from '$lib/ui/input/index'
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

  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'
  const columns: Column<any>[] = [
    { key: 'ticker', header: '标的', cell: tickerCell }, { key: 'form', header: '类型' },
    { key: 'filing_date', header: '财报日期' }, { key: 'downloaded_at', header: '下载时间', value: f => fmtTime(f.downloaded_at) },
    { key: 'file', header: '文件', cell: fileCell },
  ]
</script>

{#snippet tickerCell(f: any)}<span class="font-medium">{f.ticker}</span>{/snippet}
{#snippet fileCell(f: any)}<Button variant="link" size="sm" class="text-xs" href={api.filingDownloadUrl(f.id)} download>下载 htm</Button>{/snippet}

<div class="grid gap-3">
  <div class="flex flex-wrap items-center gap-2">
    <select aria-label="按标的筛选" bind:value={fTicker} onchange={loadFilings} class={SELECT}>
      <option value="">全部标的</option>
      {#each filingTickers as t}<option value={t}>{t}</option>{/each}
    </select>
    <select aria-label="按类型筛选" bind:value={fForm} onchange={loadFilings} class={SELECT}>
      <option value="">全部类型</option><option value="10-Q">10-Q</option><option value="10-K">10-K</option>
    </select>
    <Input aria-label="开始日期" type="date" bind:value={fFrom} onchange={loadFilings} class="w-40" />
    <span class="text-xs text-muted-foreground">至</span>
    <Input aria-label="结束日期" type="date" bind:value={fTo} onchange={loadFilings} class="w-40" />
  </div>
  {#if filings.length}
    <DataTable {columns} rows={filings} rowKey={f => f.id} ariaLabel="SEC 文件" />
  {:else}
    <DataBlock state="empty" message="暂无财报记录（可在「工具 · 任务中心」对 filings 按日期回补）" />
  {/if}
</div>
