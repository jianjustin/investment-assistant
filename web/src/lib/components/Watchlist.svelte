<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import * as wb from '../workbench'
  import { datasetName, statusName } from '../us-research-format'
  import { isCore, sectorOf, withPoolTags, SECTOR_ETFS } from '../pool-tags'
  let rows = $state<any[]>([])
  let loading = $state(true)
  let saving = $state(false)
  let error = $state('')
  let open = $state(false)
  let original = $state<any>(null)
  let ticker = $state('')
  let thesis = $state('')
  let tags = $state('')
  let status = $state('active')
  let candidates = $state<any[]>([])
  let resolveRequest = 0
  let request = 0
  let usActive = $derived(rows.filter(row => row.market === 'US' && row.status === 'active'))
  let coreCount = $derived(usActive.filter(row => isCore(row.tags ?? [])).length)
  let screenCount = $state<{ members: number; cap: number } | null>(null)

  async function load() {
    const current = ++request
    loading = true
    try {
      const result = await api.getWatchlist(true) as any
      if (current !== request) return false
      rows = result.rows ?? []
      wb.getScreen().then((out: { report: { members: number; cap: number } | null }) => {
        if (current === request) screenCount = out.report && out.report.members != null
          ? { members: out.report.members, cap: out.report.cap } : null
      }).catch(() => {})
      return true
    } catch (e) { if (current === request) error = String(e); return false }
    finally { if (current === request) loading = false }
  }
  function edit(row: any = null) {
    resolveRequest++; candidates = []; error = ''; original = row
    ticker = row?.ticker ?? ''; thesis = row?.thesis ?? ''; tags = (row?.tags ?? []).join(', ')
    status = row?.status ?? 'active'; open = true
  }
  function changedTicker() { resolveRequest++; candidates = [] }
  async function resolve() {
    const current = ++resolveRequest
    error = ''
    try {
      const result = await api.get<{ candidates: any[] }>(`/api/watchlist/resolve?symbol=${encodeURIComponent(ticker)}`)
      if (current === resolveRequest) candidates = result.candidates
    } catch (e) { if (current === resolveRequest) error = String(e) }
  }
  async function mutate(action: () => Promise<unknown>) {
    saving = true; error = ''
    try { await action(); return await load() }
    catch (e) { error = `保存失败，请核对最新记录：${String(e)}`; return false }
    finally { saving = false }
  }
  async function save() {
    const symbol = ticker.trim().toUpperCase()
    const body = { ticker: symbol, status, thesis, tags: tags.split(',').map(t => t.trim()).filter(Boolean),
      ...(original?.updated_at ? { expected_updated_at: original.updated_at } : {}) }
    if (await mutate(() => api.addWatchlistItem(body))) open = false
  }
  async function writePoolTags(row: any, core: boolean, sector: string | null) {
    // The pool tier lives in the tags; the server re-validates caps and ETF names.
    await mutate(() => api.addWatchlistItem({ ticker: row.ticker,
      tags: withPoolTags(row.tags ?? [], core, sector),
      ...(row.updated_at ? { expected_updated_at: row.updated_at } : {}) }))
  }
  async function toggle(row: any) {
    await mutate(() => api.addWatchlistItem({ ticker: row.ticker, status: row.status === 'active' ? 'paused' : 'active',
      ...(row.updated_at ? { expected_updated_at: row.updated_at } : {}) }))
  }
  onMount(load)
</script>
<div class="watchlist">
  <div class="toolbar"><h2>关注列表</h2><span class="pool-count">美股池 {usActive.length}/100 · 核心 {coreCount}/15{screenCount ? ` · 筛选 ${screenCount.members}/${screenCount.cap}` : ''}</span><button onclick={() => edit()}>+ 添加</button></div>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if loading}<p>正在读取关注列表…</p>{/if}
  <div class="table-scroll"><table><thead><tr><th>代码 / 名称</th><th>市场</th><th>状态</th><th>论点 / 标签</th><th>观察池</th><th>报告期 / 覆盖</th><th>下一事件</th><th>操作</th></tr></thead><tbody>
    {#each rows as row}<tr><td>{row.ticker}<small>{row.identity_error ?? row.name ?? '名称尚未采集'}</small></td><td>{row.market ?? '—'}</td><td>{row.status}</td><td>{row.thesis ?? '—'}<small>{(row.tags ?? []).join(' · ')}</small></td>
      <td>
        {#if row.market === 'US'}
          <label class="pool-ctl"><input type="checkbox" aria-label={`核心池 ${row.ticker}`} checked={isCore(row.tags ?? [])}
                 onchange={e => writePoolTags(row, e.currentTarget.checked, sectorOf(row.tags ?? []))} disabled={saving} />核心</label>
          <select aria-label={`行业 ETF ${row.ticker}`} value={sectorOf(row.tags ?? []) ?? ''}
                  onchange={e => writePoolTags(row, isCore(row.tags ?? []), e.currentTarget.value || null)} disabled={saving}>
            <option value="">未映射</option>
            {#each SECTOR_ETFS as etf}<option value={etf}>{etf}</option>{/each}
          </select>
        {:else}—{/if}
      </td>
      <td>{row.latest_period ?? '尚未采集'}<small>{Object.entries(row.datasets ?? {}).map(([key, value]) => `${datasetName(key)}: ${statusName((value as any).status)}`).join(' · ') || '尚无本地数据'}</small></td>
      <td>{row.next_event?.date ?? '尚无财报日'}<small>{row.next_event?.title ?? ({earnings:'财报'}[row.next_event?.kind as string] ?? '')}</small></td>
      <td><button disabled={saving || !!row.identity_error} onclick={() => edit(row)}>编辑</button><button disabled={saving || !!row.identity_error} onclick={() => toggle(row)}>{row.status === 'active' ? '暂停' : '恢复'}</button><button disabled={saving} onclick={() => mutate(() => api.deleteWatchlistItem(row.ticker))}>删除</button></td></tr>
    {:else}<tr><td colspan="8">暂无关注证券</td></tr>{/each}
  </tbody></table></div>
  {#if open}<section aria-label={original ? '编辑关注' : '添加关注'}>
    <h3>{original ? '编辑关注' : '添加关注'}</h3>
    <label>证券代码<input aria-label="证券代码" bind:value={ticker} oninput={changedTicker} disabled={!!original || saving} placeholder="MU / BRK.B" /></label>
    {#if !original}<button onclick={resolve} disabled={saving || !ticker}>确认身份</button>{/if}
    {#each candidates as candidate}<button onclick={() => { ticker = candidate.symbol; changedTicker() }}>{candidate.symbol} {candidate.name ?? ''}</button>{/each}
    <label>论点<input aria-label="论点" bind:value={thesis} /></label>
    <label>标签<input aria-label="标签" bind:value={tags} placeholder="用逗号分隔" /></label>
    <label>状态<select bind:value={status}><option value="active">active</option><option value="paused">paused</option></select></label>
    <button onclick={save} disabled={saving}>保存</button><button onclick={() => { resolveRequest++; open = false }} disabled={saving}>取消</button>
  </section>{/if}
</div>
<style>
  .watchlist{display:grid;gap:1rem}.toolbar{display:flex;align-items:center;gap:.7rem}.toolbar{justify-content:space-between}h2,h3{font-weight:600}button,input,select{padding:.4rem .6rem;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text)}button:disabled{opacity:.45}.table-scroll{overflow:auto}table{width:100%;font-size:.82rem;border-collapse:collapse}td,th{text-align:left;padding:.7rem;border-bottom:1px solid var(--border)}small{display:block;color:var(--text-muted);margin-top:.3rem}td button{margin:.2rem}section{display:flex;flex-wrap:wrap;gap:.7rem;padding:1rem;border:1px solid var(--border)}.pool-count{font-size:.82rem;color:var(--text-muted)}.pool-ctl{white-space:nowrap;font-size:.8rem}td select{margin-left:.3rem;padding:.2rem .3rem;font-size:.78rem}label{display:grid;gap:.3rem}p[role=alert]{color:#bd5d23}
</style>
