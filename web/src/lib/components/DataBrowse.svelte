<script lang="ts">
  import * as api from '../api'
  import { fmtBeijing, fmtPct } from '../format'
  import { extraEvidence, fetchTarget, noteText, type BrowseResult, type FamilyCard } from '../data-families'
  import CodeText from './CodeText.svelte'

  let { family, targets, onfetched, pageEvidence = '' }: {
    family: FamilyCard
    targets: string[]
    onfetched?: () => void | Promise<void>
    pageEvidence?: string   // the page banner; only the family's supplement is repeated here
  } = $props()
  let evidence = $derived(extraEvidence(family.evidence, pageEvidence))

  let ticker = $state('')
  let draft = $state('')
  let series = $state('BAMLH0A0HYM2')
  let result = $state<BrowseResult | null>(null)
  let loading = $state(false)
  let error = $state('')
  let busy = $state(false)
  let fetchError = $state('')
  let fetchNote = $state('')
  let fetchOrigin = $state<{ family: FamilyCard['id']; ticker: string } | null>(null)
  let generation = 0
  let byTicker = $derived(family.id !== 'fred' && family.id !== 'universe')
  let showFetchResult = $derived(fetchOrigin?.family === family.id && fetchOrigin?.ticker === ticker)

  $effect(() => { if (!ticker && targets.length) ticker = targets[0] })
  $effect(() => { draft = ticker })

  async function load() {
    const id = family.id
    const params = id === 'fred' ? { series } : id === 'universe' ? {} : { ticker }
    const token = ++generation
    result = null
    error = ''
    if (id !== 'fred' && id !== 'universe' && !ticker) { loading = false; return }
    loading = true
    try {
      const next = await api.browseData(id, params)
      if (token === generation) result = next
    } catch (e) {
      if (token === generation) error = String((e as Error)?.message ?? e)
    } finally {
      if (token === generation) loading = false
    }
  }

  $effect(() => {
    // A refreshed card also refreshes raw values, without resetting the selection.
    family; ticker; series
    load()
    return () => { generation++ }
  })

  function selectTicker(event: SubmitEvent) {
    event.preventDefault()
    draft = draft.trim().toUpperCase()
    ticker = draft
  }

  async function fetchOne() {
    const target = draft.trim().toUpperCase()
    if (busy || !family.per_ticker || !target) return
    const fetchId = fetchTarget(family)
    // Keep asynchronous outcomes attached to the family/ticker that started the run.
    fetchOrigin = { family: family.id, ticker: target }
    ticker = target
    draft = target
    busy = true
    fetchError = ''
    fetchNote = ''
    try {
      const pending = await api.fetchDataFamily(fetchId, target)
      const run = await api.pollRun(pending.run_id, { timeoutMs: 900_000 })
      const outcome = run.result as {
        status?: string; data_status?: { error?: string | null }
        row?: { failures?: { target: string; reason: string }[] }
      } | undefined
      const messages: string[] = []
      if (run.status === 'error') messages.push(run.error ?? '运行失败')
      else if (outcome?.status === 'busy') messages.push('该族正在采集')
      else if (outcome?.status === 'partial' || outcome?.status === 'failed') {
        messages.push(outcome.status === 'partial' ? '部分失败' : '拉取失败')
        for (const failure of outcome.row?.failures ?? []) messages.push(`${failure.target}：${failure.reason}`)
      }
      if (outcome?.data_status?.error) messages.push(`采集记录写入失败：${outcome.data_status.error}`)
      fetchError = messages.join('；')
      if (!fetchError) fetchNote = '拉取完成'
      await onfetched?.()
      await load()
    } catch (e) {
      const message = String((e as Error)?.message ?? e)
      if (message === 'run timeout') fetchNote = '仍在后台运行，稍后刷新'
      else fetchError = [fetchError, message].filter(Boolean).join('；')
    } finally {
      busy = false
    }
  }

  type Row = Record<string, unknown>
  type Column = { key: string; label: string; format?: (value: unknown) => string; link?: string }
  const text = (value: unknown): string => value == null ? '—' : Array.isArray(value) ? value.join(', ') : String(value)
  const columns: Record<string, Column[]> = {
    bars: [
      { key: 'price_date', label: '日期' }, { key: 'open', label: '开' }, { key: 'high', label: '高' },
      { key: 'low', label: '低' }, { key: 'close', label: '收' }, { key: 'adj_close', label: 'adj_close' },
      { key: 'volume', label: '成交量' }, { key: 'split_factor', label: '拆股因子' },
      { key: 'revisions', label: '修订次数' }, { key: 'fetched_at', label: '采集时间', format: fmtBeijing },
    ],
    atr: [
      { key: 'price_date', label: '日期' }, { key: 'close', label: 'close' }, { key: 'atr', label: 'atr' },
      { key: 'atr_pct', label: 'atr_pct（ATR/收盘）', format: value => fmtPct(value as number | null) },
    ],
    news: [
      { key: 'title', label: '标题 / 链接', link: 'url' }, { key: 'source', label: '来源' },
      { key: 'publisher', label: '发布者' }, { key: 'published_at', label: '发布时间', format: fmtBeijing },
    ],
    sec_filings: [
      { key: 'ticker', label: '标的' }, { key: 'form', label: '类型' }, { key: 'filing_date', label: '申报日期' },
      { key: 'accession_number', label: '申报编号' }, { key: 'primary_document', label: '主文档' },
      { key: 'accepted_at', label: '接收时间', format: fmtBeijing }, { key: 'items', label: '条目' },
    ],
    sec_8k: [
      { key: 'title', label: '标题 / 链接', link: 'url' }, { key: 'publisher', label: '发布者' },
      { key: 'published_at', label: '发布时间', format: fmtBeijing },
      { key: 'filing_date_note', label: '申报日期' },
    ],
    fred: [{ key: 'obs_date', label: '观测日期' }, { key: 'value', label: '实际值' }, { key: 'revisions', label: '修订次数' }],
    universe: [{ key: 'ticker', label: '标的' }, { key: 'latest_bar', label: '最近日线日期' }],
  }
  const tableNames: Record<string, string> = {
    bars: '日线原始值', atr: 'ATR 原始值', news: '资讯原始值', fred: 'FRED 原始值', universe: '范围成员',
  }
  let rows = $derived(Array.isArray(result?.rows) ? result.rows : [])
</script>

{#snippet rawTable(label: string, values: Row[], fields: Column[])}
  <div class="overflow-x-auto border border-border rounded bg-surface">
    <table aria-label={label} class="w-full text-sm text-left whitespace-nowrap">
      <thead><tr class="text-muted">
        {#each fields as column}<th class="px-3 py-2">{column.label}</th>{/each}
      </tr></thead>
      <tbody>
        {#each values as row}
          <tr class="border-t border-border">
            {#each fields as column}
              <td class="px-3 py-2">
                {#if column.link && row[column.link]}
                  <a href={String(row[column.link])} target="_blank" rel="noopener noreferrer" class="text-accent underline whitespace-normal break-words">{text(row[column.key])}</a>
                {:else}{(column.format ?? text)(row[column.key])}{/if}
              </td>
            {/each}
          </tr>
        {:else}<tr><td colspan={fields.length} class="px-3 py-3 text-muted">无记录</td></tr>{/each}
      </tbody>
    </table>
  </div>
{/snippet}

<section aria-label="原始数据浏览" class="space-y-3 min-w-0">
  <h2 class="font-semibold">原始数据浏览</h2>
  {#if evidence}<p class="text-xs text-muted"><CodeText text={evidence} /></p>{/if}
  {#if byTicker}
    <form onsubmit={selectTicker} class="flex flex-wrap items-center gap-2">
      <label class="text-sm" for="browse-ticker">标的</label>
      <input id="browse-ticker" list="browse-targets" bind:value={draft} disabled={busy}
             class="text-sm border border-border rounded px-2 py-1 bg-surface" placeholder="选择或输入标的" />
      <datalist id="browse-targets">{#each targets as target}<option value={target}></option>{/each}</datalist>
      <button type="submit" disabled={busy} class="text-xs px-2 py-1 rounded border border-border">浏览</button>
      {#if family.per_ticker}
        <button type="button" disabled={busy || !draft.trim()} onclick={fetchOne}
                class="text-xs px-2 py-1 rounded bg-accent text-white disabled:opacity-50">{busy ? '采集中…' : '只拉这一只'}</button>
      {/if}
    </form>
  {:else if family.id === 'fred'}
    <label class="text-sm">FRED 序列
      <select bind:value={series} class="text-sm border border-border rounded px-2 py-1 bg-surface">
        <option value="BAMLH0A0HYM2">BAMLH0A0HYM2</option><option value="T10Y2Y">T10Y2Y</option>
      </select>
    </label>
  {/if}
  {#if showFetchResult}
    {#if fetchError}<p class="text-xs text-red-600">{fetchError}</p>{/if}
    {#if fetchNote}<p class="text-xs text-muted">{fetchNote}</p>{/if}
  {/if}
  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading}
    <p class="text-sm text-muted">加载中…</p>
  {:else if result}
    {#each result.notes ?? [] as note}<p class="text-xs text-warn">{noteText(note)}</p>{/each}
    {#if result.current_error}<p class="text-xs text-warn">{result.current_error}</p>{/if}
    {#if family.id === 'bars'}
      <p class="text-xs text-muted">{text(rows[0]?.note ?? '拆股调整、未分红调整；adj_close 全调整')}</p>
    {:else if family.id === 'atr'}
      <p class="text-xs text-muted"><CodeText text={result.note ?? '现算，与 `plan-1` 同一函数；不入库'} /></p>
    {/if}
    {#if family.id === 'universe' && result.meta}
      <dl class="text-sm grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 break-words">
        {#each ['name', 'as_of', 'source', 'note'] as field}
          <dt class="text-muted">{field}</dt><dd class="min-w-0">{text(result.meta[field])}</dd>
        {/each}
      </dl>
    {/if}
    {#if !result.has_data}
      <p class="text-sm text-muted">无数据，可点拉取</p>
    {:else if family.id === 'sec_filings'}
      <h3 class="text-sm font-medium">filings</h3>
      {@render rawTable('filings', result.filings ?? [], columns.sec_filings)}
      <h3 class="text-sm font-medium">sec_8k（未入 filings）</h3>
      {@render rawTable('sec_8k（未入 filings）', result.sec_8k ?? [], columns.sec_8k)}
    {:else}
      {@render rawTable(tableNames[family.id], rows, columns[family.id])}
    {/if}
  {:else if byTicker}
    <p class="text-sm text-muted">请选择或输入标的</p>
  {/if}
</section>
