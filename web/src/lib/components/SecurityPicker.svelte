<script lang="ts">
  import * as api from '../api'
  let { market, value, onchange, beforeChange, onloaded }: {
    market: 'CN' | 'US'; value: string; onchange: (symbol: string) => void
    beforeChange?: () => boolean; onloaded?: (rows: any[]) => void
  } = $props()
  let rows = $state<any[]>([])
  let error = $state('')
  let loading = $state(false)
  let request = 0
  $effect(() => {
    const selectedMarket = market
    const current = ++request
    loading = true
    error = ''
    api.getWatchlist(selectedMarket, true).then((result: any) => {
      if (current !== request) return
      rows = (result.rows ?? []).filter((r: any) => r.status === 'active' && !r.identity_error)
      onloaded?.(rows)
    }).catch(e => { if (current === request) error = String(e) })
      .finally(() => { if (current === request) loading = false })
    return () => { request++ }
  })
  function change(event: Event) {
    const select = event.currentTarget as HTMLSelectElement
    const next = select.value
    if (beforeChange?.() === false) { select.value = value; return }
    onchange(next)
  }
</script>
<label>关注证券
  <select aria-label="关注证券" {value} onchange={change} disabled={loading || !rows.length}>
    {#if !rows.length}<option value="">暂无关注证券</option>{/if}
    {#if value && !rows.some(r => r.ticker === value)}<option value={value}>{value}</option>{/if}
    {#each rows as row}<option value={row.ticker}>{row.ticker} {row.name ?? ''}</option>{/each}
  </select>
</label>
{#if error}<p role="alert">读取关注列表失败：{error}</p>{/if}
<style>label{min-width:0;max-width:100%;display:grid;gap:.25rem;font-size:.8rem}select{min-width:0;max-width:100%;padding:.5rem;border:1px solid var(--border);background:var(--surface-2);color:var(--text);border-radius:5px}</style>
