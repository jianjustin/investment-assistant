<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import * as wb from '../workbench'
  import { datasetName, statusName } from '../us-research-format'
  import { isCore, sectorOf, withPoolTags, SECTOR_ETFS } from '../pool-tags'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import PageHeader from '$lib/ui/domain/PageHeader.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  const uid = $props.id()
  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground disabled:opacity-50'
  const columns: Column<any>[] = [
    { key: 'ticker', header: '代码 / 名称', cell: tickerCell },
    { key: 'market', header: '市场', value: row => row.market ?? '未设置' },
    { key: 'status', header: '状态' },
    { key: 'thesis', header: '论点 / 标签', cell: thesisCell },
    { key: 'pool', header: '观察池', cell: poolCell },
    { key: 'coverage', header: '报告期 / 覆盖', cell: coverageCell },
    { key: 'event', header: '下一事件', cell: eventCell },
    { key: 'actions', header: '操作', cell: actionsCell },
  ]
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
{#snippet tickerCell(row: any)}<span>{row.ticker}</span><small class="mt-1 block text-xs text-muted-foreground">{row.identity_error ?? row.name ?? '名称尚未采集'}</small>{/snippet}
{#snippet thesisCell(row: any)}<span>{row.thesis ?? '未填写'}</span><small class="mt-1 block text-xs text-muted-foreground">{(row.tags ?? []).join(' · ')}</small>{/snippet}
{#snippet poolCell(row: any)}
  {#if row.market === 'US'}
    <div class="flex flex-wrap items-center gap-2">
      <label class="flex items-center gap-1 whitespace-nowrap text-xs"><input type="checkbox" class="size-4 accent-primary" aria-label={`核心池 ${row.ticker}`} checked={isCore(row.tags ?? [])}
             onchange={e => writePoolTags(row, e.currentTarget.checked, sectorOf(row.tags ?? []))} disabled={saving} />核心</label>
      <select aria-label={`行业 ETF ${row.ticker}`} class="h-7 rounded-md border border-input bg-card px-1.5 text-xs text-foreground disabled:opacity-50" value={sectorOf(row.tags ?? []) ?? ''}
              onchange={e => writePoolTags(row, isCore(row.tags ?? []), e.currentTarget.value || null)} disabled={saving}>
        <option value="">未映射</option>
        {#each SECTOR_ETFS as etf}<option value={etf}>{etf}</option>{/each}
      </select>
    </div>
  {:else}—{/if}
{/snippet}
{#snippet coverageCell(row: any)}<span>{row.latest_period ?? '尚未采集'}</span><small class="mt-1 block text-xs text-muted-foreground">{Object.entries(row.datasets ?? {}).map(([key, value]) => `${datasetName(key)}: ${statusName((value as any).status)}`).join(' · ') || '尚无本地数据'}</small>{/snippet}
{#snippet eventCell(row: any)}<span>{row.next_event?.date ?? '尚无财报日'}</span><small class="mt-1 block text-xs text-muted-foreground">{row.next_event?.title ?? ({earnings:'财报'}[row.next_event?.kind as string] ?? '')}</small>{/snippet}
{#snippet actionsCell(row: any)}
  <div class="flex flex-wrap gap-1">
    <Button size="sm" disabled={saving || !!row.identity_error} onclick={() => edit(row)}>编辑</Button>
    <Button size="sm" disabled={saving || !!row.identity_error} onclick={() => toggle(row)}>{row.status === 'active' ? '暂停' : '恢复'}</Button>
    <Button size="sm" disabled={saving} onclick={() => mutate(() => api.deleteWatchlistItem(row.ticker))}>删除</Button>
  </div>
{/snippet}

<div class="grid gap-4">
  <PageHeader level={2} title="关注列表">
    {#snippet meta()}<span>美股池 {usActive.length}/100 · 核心 {coreCount}/15{screenCount ? ` · 筛选 ${screenCount.members}/${screenCount.cap}` : ''}</span>{/snippet}
    {#snippet actions()}<Button variant="primary" onclick={() => edit()}>+ 添加</Button>{/snippet}
  </PageHeader>
  {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}
  {#if loading}<p class="text-sm text-muted-foreground">正在读取关注列表…</p>{/if}
  {#if rows.length}
    <div class="overflow-x-auto">
      <DataTable {columns} {rows} rowKey={row => row.ticker} ariaLabel="关注列表" sticky={false} />
    </div>
  {:else if !loading}
    <DataBlock state="empty" message="暂无关注证券" />
  {/if}
  {#if open}
    <Card.Root role="region" aria-label={original ? '编辑关注' : '添加关注'} size="sm" class="px-3">
      <h3 class="text-base font-medium">{original ? '编辑关注' : '添加关注'}</h3>
      <div class="flex flex-wrap items-end gap-3">
        <Field label="证券代码" id={`${uid}-ticker`}>
          {#snippet children({ id, describedby })}
            <Input {id} aria-describedby={describedby} bind:value={ticker} oninput={changedTicker} disabled={!!original || saving} placeholder="MU / BRK.B" />
          {/snippet}
        </Field>
        {#if !original}<Button onclick={resolve} disabled={saving || !ticker}>确认身份</Button>{/if}
        {#each candidates as candidate}<Button onclick={() => { ticker = candidate.symbol; changedTicker() }}>{candidate.symbol} {candidate.name ?? ''}</Button>{/each}
      </div>
      <div class="grid gap-3 sm:grid-cols-3">
        <Field label="论点" id={`${uid}-thesis`}>
          {#snippet children({ id, describedby })}<Input {id} aria-describedby={describedby} bind:value={thesis} />{/snippet}
        </Field>
        <Field label="标签" id={`${uid}-tags`}>
          {#snippet children({ id, describedby })}<Input {id} aria-describedby={describedby} bind:value={tags} placeholder="用逗号分隔" />{/snippet}
        </Field>
        <Field label="状态" id={`${uid}-status`}>
          {#snippet children({ id, describedby })}
            <select {id} aria-describedby={describedby} class={SELECT} bind:value={status}><option value="active">active</option><option value="paused">paused</option></select>
          {/snippet}
        </Field>
      </div>
      <div class="flex gap-2">
        <Button variant="primary" onclick={save} busy={saving}>保存</Button>
        <Button onclick={() => { resolveRequest++; open = false }} disabled={saving}>取消</Button>
      </div>
    </Card.Root>
  {/if}
</div>
