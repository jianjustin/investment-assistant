<script lang="ts">
  import { onMount, untrack } from 'svelte'
  import { getWatchlist } from '../lib/api'
  import * as wb from '../lib/workbench'

  let { sub }: { sub?: string } = $props()

  let ticker = $state('')
  let tickers = $state<string[]>([])
  let view = $state<wb.InstrumentView | null>(null)
  let error = $state('')
  let loading = $state(false)
  let generation = 0

  const KIND_LABELS: Record<wb.TimelineItem['kind'], string> = {
    filing: '财报', news: '资讯', candidate: '信号', decision: '决定', trade: '成交',
  }

  async function select(next: string, updateHash = true) {
    next = next.trim().toUpperCase()
    if (!next || next === ticker) return
    ticker = next
    if (updateHash) history.replaceState(null, '', `#instrument/${next}`)
    const token = ++generation
    loading = true
    error = ''
    view = null
    try {
      const loaded = await wb.getInstrument(next)
      if (token !== generation) return
      // A late response for another ticker must never be shown under this one.
      if (loaded.ticker !== next) throw new Error('响应标的不匹配')
      view = loaded
    } catch (e) {
      if (token === generation) error = wb.describeError(e)
    } finally {
      if (token === generation) loading = false
    }
  }

  // Only a route change selects; untracked so selecting from the picker is not undone.
  $effect(() => {
    const routed = sub
    untrack(() => { if (routed) select(routed, false) })
  })

  onMount(async () => {
    try {
      const rows = (await getWatchlist()) as { rows?: { ticker: string }[] }
      tickers = (rows.rows ?? []).map(r => r.ticker)
      if (!sub && tickers[0]) select(tickers[0])
    } catch {
      tickers = []
    }
  })
</script>

<section class="space-y-4">
  <header class="flex items-center gap-3">
    <h1 class="text-lg font-semibold">标的</h1>
    <select aria-label="标的" class="border border-border rounded px-2 py-1 text-sm bg-bg" value={ticker}
            onchange={e => select((e.currentTarget as HTMLSelectElement).value)}>
      {#if ticker && !tickers.includes(ticker)}<option value={ticker}>{ticker}</option>{/if}
      {#each tickers as t}<option value={t}>{t}</option>{/each}
    </select>
  </header>

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading}
    <p class="text-sm text-muted">加载中…</p>
  {:else if !ticker}
    <p class="text-sm text-muted">观察名单为空，请在「更多 → 设置 → 关注列表」添加美股。</p>
  {/if}

  {#if view}
    <h2 class="font-semibold">{view.ticker} · 截至 {view.session}</h2>
    {#if view.position}
      <p class="text-sm">持仓 {view.position.quantity} 股 · 成本 {Number(view.position.avg_cost).toFixed(2)} · 开仓 {wb.dateTime(view.position.opened_at)}</p>
    {:else}
      <p class="text-sm text-muted">当前无持仓</p>
    {/if}
    {#if view.bars.length}
      {@const last = view.bars[view.bars.length - 1]}
      <p class="text-xs text-muted">最新日线 {last.price_date}：开 {last.open} · 收 {last.close}（拆股调整、未分红调整）</p>
    {/if}
    <ol class="space-y-1 text-sm">
      {#each wb.timeline(view) as item}
        <li class="flex gap-2">
          <span class="text-xs text-muted w-32 shrink-0">{wb.dateTime(item.at)}</span>
          <span class="text-xs px-1 rounded bg-surface-2 shrink-0">{KIND_LABELS[item.kind]}</span>
          {#if item.url}<a class="underline" href={item.url} target="_blank" rel="noreferrer">{item.text}</a>{:else}<span>{item.text}</span>{/if}
        </li>
      {:else}
        <li class="text-muted">暂无记录</li>
      {/each}
    </ol>
  {/if}
</section>
