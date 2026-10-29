<script module lang="ts">
  import * as api from '../api'
  import type { RunOverviewView } from '../knowledge'

  // Lines that mount together (the principles page shows one line per stage) share one request.
  const pending = new Map<string, Promise<RunOverviewView>>()
  function fetchOverview(session?: string, runId?: string): Promise<RunOverviewView> {
    const key = `${session ?? ''}|${runId ?? ''}`
    let request = pending.get(key)
    if (!request) {
      request = new Promise<RunOverviewView>(resolve => resolve(api.getRunOverview(session, runId)))   // a sync throw becomes a rejection
      const current = request
      const forget = () => { if (pending.get(key) === current) pending.delete(key) }
      current.then(forget, forget)
      pending.set(key, current)
    }
    return request
  }
</script>

<script lang="ts">
  import ConceptTerm from './ConceptTerm.svelte'
  import { ATTACH, type StageLine } from '../knowledge'
  import { fmtBeijing } from '../format'
  import { RUN_ID_RE, runHref } from '../runs'

  // 运行一览（spec §7.5）。session 给了就跟着它走（原理页）；不给就用自己的日期选择，缺省 = 最近已收盘交易日。
  // compact 去掉页头；onlyStage 只画一个阶段（原理页「当天这一步」）。
  let { session, compact = false, onlyStage }:
    { session?: string; compact?: boolean; onlyStage?: string } = $props()

  let picked = $state('')          // 日期选择（session 未给时）
  let runId = $state('')           // 同日多次运行时选中的运行
  let ov = $state<RunOverviewView | null>(null)
  let error = $state('')
  let loading = $state(true)
  let folded = $state(false)       // 折叠状态不保存
  let expanded = $state<Record<string, boolean>>({})
  let generation = 0

  $effect(() => {
    const day = session ?? (picked || undefined)
    const run = session === undefined ? (runId || undefined) : undefined
    const token = ++generation
    loading = true
    fetchOverview(day, run).then(next => {
      if (token !== generation) return
      // Tolerate a response without the expected lists instead of breaking the page it sits on.
      ov = { ...next, runs: next.runs ?? [], stages: next.stages ?? [] }
      error = ''
    }).catch((e: unknown) => {
      if (token !== generation) return
      error = String((e as Error)?.message ?? e)
      ov = null
    }).finally(() => { if (token === generation) loading = false })
    return () => { generation++ }
  })

  function pickDay(event: Event) {
    picked = (event.currentTarget as HTMLInputElement).value
    runId = ''
  }
  function pickRun(event: Event) {
    runId = (event.currentTarget as HTMLSelectElement).value
  }

  const lines = $derived((ov?.stages ?? []).filter(s => !onlyStage || s.id === onlyStage))
  const count = (value: number | null) => value == null ? '—' : String(value)
  function duration(ms: number | null): string {
    if (ms == null) return ''
    if (ms < 1000) return `${ms} 毫秒`
    const seconds = ms / 1000
    if (seconds < 60) return `${seconds.toFixed(1)} 秒`
    return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
  }
  const hasDetail = (s: StageLine) => s.skips.length > 0 || s.failures.length > 0 || s.degradations.length > 0
  const runLabel = (r: { trigger_text: string; started_at: string | null }) =>
    `${r.trigger_text} · ${r.started_at ? fmtBeijing(r.started_at).slice(11, 16) + ' 北京' : '时间未知'}`
  const STATUS_CLASS: Record<string, string> = {
    success: 'bg-success/20 text-success', partial: 'bg-warn/20 text-warn', degraded: 'bg-warn/20 text-warn',
    failed: 'bg-danger/20 text-danger', skipped: 'bg-surface-2 text-muted', missing: 'bg-danger/20 text-danger',
    not_recorded: 'bg-surface-2 text-muted',
  }
</script>

<section aria-label="运行一览" class="border border-border rounded p-3 bg-surface text-sm space-y-2">
  {#if !compact && !onlyStage}
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h2 class="font-semibold">运行一览</h2>
      {#if ov?.selected_run_id && RUN_ID_RE.test(ov.selected_run_id)}
        <a class="text-xs text-accent underline" href={runHref(ov.selected_run_id)}>运行详情</a>
      {/if}
      {#if ov?.headline}<span class="text-xs text-muted">{ov.headline}</span>{/if}
      <input type="date" aria-label="日期" class="text-xs border border-border rounded px-1 py-0.5 bg-bg"
             value={ov?.session ?? picked} onchange={pickDay} />
      {#if ov && ov.runs.length > 1}
        <select aria-label="运行" class="text-xs border border-border rounded px-1 py-0.5 bg-bg"
                value={ov.selected_run_id ?? ''} onchange={pickRun}>
          {#each ov.runs as r (r.run_id)}<option value={r.run_id}>{runLabel(r)}</option>{/each}
        </select>
      {/if}
      <a class="text-xs text-accent underline" href="#knowledge/principles">原理</a>
      <button type="button" class="text-xs px-2 py-0.5 border border-border rounded hover:bg-surface-2"
              aria-expanded={!folded} onclick={() => folded = !folded}>{folded ? '展开运行一览' : '收起运行一览'}</button>
    </header>
  {:else if onlyStage && ov}
    <p class="text-xs text-muted">当天这一步（{ov.session}）</p>
  {/if}

  {#if error}
    <p role="alert" class="text-xs text-red-600">{error}</p>
  {:else if loading && !ov}
    <p class="text-xs text-muted">加载中…</p>
  {:else if ov}
    {#if ov.note}<p class="text-xs text-muted">{ov.note}</p>{/if}
    {#if !folded || compact || onlyStage}
      <ul class="space-y-1">
        {#each lines as s (s.id)}
          <li class="space-y-0.5">
            <div class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span class="font-medium"><ConceptTerm id={ATTACH.overview.stages}>{s.title}</ConceptTerm></span>
              <span class="text-xs px-1.5 py-0.5 rounded {STATUS_CLASS[s.status] ?? 'bg-surface-2 text-muted'}"><ConceptTerm id={ATTACH.overview.status}>{s.status_text}</ConceptTerm></span>
              <span>{s.sentence}</span>
              {#each s.concepts as concept, i (i)}<span class="text-xs"><ConceptTerm id={concept} /></span>{/each}
              <span class="text-xs text-muted">输入 {count(s.input_count)} · 产出 {count(s.output_count)}</span>
              {#if s.duration_ms != null}<span class="text-xs text-muted">{duration(s.duration_ms)}</span>{/if}
              {#if hasDetail(s)}
                <button type="button" class="text-xs text-accent underline" aria-expanded={!!expanded[s.id]}
                        onclick={() => expanded[s.id] = !expanded[s.id]}>{expanded[s.id] ? '收起明细' : '展开明细'}</button>
              {/if}
            </div>
            {#if expanded[s.id]}
              <div class="ml-4 text-xs space-y-0.5">
                {#each s.skips as skip, i (i)}
                  <p>{skip.text} × {skip.count}{skip.samples.length ? `（样本：${skip.samples.join('、')}）` : ''}</p>
                {/each}
                {#each s.failures as failure, i (i)}
                  <p class="text-red-600">{failure.target}：{failure.reason}</p>
                {/each}
                {#each s.degradations as d, i (i)}
                  <p class="text-amber-700">{d.text}{d.detail ? `：${d.detail}` : ''}</p>
                {/each}
              </div>
            {/if}
          </li>
        {:else}
          {#if onlyStage}<li class="text-xs text-muted">这一天没有这一阶段的证据</li>{/if}
        {/each}
      </ul>
    {/if}
  {/if}
</section>
