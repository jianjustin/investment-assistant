<script lang="ts">
  import { onMount } from 'svelte'
  import { registerNavigationGuard } from '../lib/navigation-guard'
  import * as wb from '../lib/workbench'

  type Draft = { choice: wb.Choice; reason: string; requestId: string; error: string; busy: boolean }

  let view = $state<wb.TodayView | null>(null)
  let error = $state('')
  let loading = $state(true)
  let notice = $state('')
  let drafts = $state<Record<string, Draft>>({})
  let generation = 0

  const keyOf = (u: wb.Unit) => `${u.ticker}|${u.signal_date}`

  async function load() {
    const token = ++generation
    loading = true
    try {
      const next = await wb.getToday()
      if (token !== generation) return
      for (const u of next.units) {
        // Drafts survive reloads and failed submits; the request id stays the same until success.
        drafts[keyOf(u)] ??= { choice: 'accept', reason: '', requestId: wb.newRequestId(), error: '', busy: false }
      }
      view = next
      error = ''
    } catch (e) {
      if (token === generation) { error = wb.describeError(e); view = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  async function submit(u: wb.Unit) {
    const key = keyOf(u)
    const draft = drafts[key]
    if (!draft || !draft.reason.trim() || draft.busy) return
    draft.busy = true
    draft.error = ''
    try {
      await wb.postDecision(wb.decisionPayload(u, draft.choice, draft.reason, draft.requestId))
      delete drafts[key]
      await load()
    } catch (e) {
      draft.error = wb.describeError(e)
    } finally {
      if (drafts[key]) drafts[key].busy = false
    }
  }

  async function runNow() {
    try {
      const run = await wb.runWorkbench()
      notice = `已提交批处理（${run.run_id}），完成后刷新本页查看。`
    } catch (e) {
      notice = wb.describeError(e)
    }
  }

  const values = (c: wb.Candidate) =>
    Object.entries(c.inputs?.values ?? {}).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join('/') : v}`).join(' · ')

  onMount(() => {
    load()
    return registerNavigationGuard({
      snapshot: () => JSON.stringify(Object.entries(drafts).map(([k, d]) => [k, d.choice, d.reason])),
      dirty: () => Object.values(drafts).some(d => d.reason.trim() !== ''),
      discard: () => { for (const d of Object.values(drafts)) d.reason = '' },
    })
  })
</script>

<section class="space-y-4">
  <header class="flex items-center justify-between">
    <div>
      <h1 class="text-lg font-semibold">今日</h1>
      {#if view}<p class="text-xs text-muted">最近收盘交易日 {view.session} · 信号仅为研究候选，不会自动下单</p>{/if}
    </div>
    <button class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2" onclick={runNow}>立即运行批处理</button>
  </header>
  {#if notice}<p class="text-xs text-muted">{notice}</p>{/if}

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading && !view}
    <p class="text-sm text-muted">加载中…</p>
  {:else if view && view.units.length === 0}
    <p class="text-sm text-muted">今日没有待处理的信号</p>
  {/if}

  {#each view?.units ?? [] as u (keyOf(u))}
    {@const draft = drafts[keyOf(u)]}
    <article class="border border-border rounded p-3 space-y-3 bg-surface">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="font-semibold">{u.ticker} · {u.signal_date}</h2>
        <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">建议{wb.ACTION_LABELS[u.proposed_action]}</span>
        {#each u.labels as label}<span class="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">{wb.UNIT_LABELS[label] ?? label}</span>{/each}
        {#if u.entry_passed}<span class="text-xs text-amber-700">已过入场时点（T+1 开盘）</span>{/if}
        {#if u.market_status}<span class="text-xs text-muted">大盘 {u.market_status}（仅背景）</span>{/if}
        {#if u.position}<span class="text-xs text-muted">持仓 {u.position.quantity} · 成本 {Number(u.position.avg_cost).toFixed(2)}</span>{/if}
      </div>

      <ul class="text-sm space-y-1">
        {#each u.candidates as c (c.id)}
          <li><span class="font-medium">{wb.ruleLabel(c.rule_id)}</span> → {wb.ACTION_LABELS[c.action]} <span class="text-xs text-muted">{values(c)}</span></li>
        {/each}
      </ul>

      <div class="text-sm border-l-2 border-border pl-2 space-y-1">
        {#if !u.brief}
          <p class="text-muted">尚无解读</p>
        {:else if u.brief.status === 'error'}
          <p class="text-red-600">解读无效，已隐藏：{u.brief.error}</p>
        {:else}
          {#if u.brief.status === 'fallback'}<p class="text-xs text-muted">规则版解读（LLM 未参与：{u.brief.error}）</p>{/if}
          <p>{u.brief.output?.summary}</p>
          {#each [['支持', u.brief.output?.support], ['反证', u.brief.output?.contra], ['冲突与缺口', u.brief.output?.conflicts]] as [title, items]}
            {#if Array.isArray(items) && items.length}
              <p class="text-xs text-muted">{title}</p>
              <ul class="list-disc ml-5">
                {#each items as item}<li>{item.text}（{item.refs.join(', ')}）</li>{/each}
              </ul>
            {/if}
          {/each}
        {/if}
      </div>

      {#if u.filings.length || u.news.length}
        <ul class="text-xs space-y-0.5 text-muted">
          {#each u.filings as f (f.id)}
            <li>SEC {f.form}{f.items?.length ? `（Items ${f.items.join(', ')}）` : ''} · {f.accepted_at ? wb.dateTime(f.accepted_at) : '受理时间未知'}</li>
          {/each}
          {#each u.news as n (n.id)}
            <li><a class="underline" href={n.url} target="_blank" rel="noreferrer">{n.title}</a> · {n.publisher ?? n.source} · {wb.publishedText(n.published_at)}</li>
          {/each}
        </ul>
      {/if}

      {#if draft}
        <form class="space-y-2" onsubmit={e => { e.preventDefault(); submit(u) }}>
          <fieldset class="flex gap-3 text-sm">
            {#each (u.proposed_action === 'watch' ? ['accept', 'reject'] : ['accept', 'reject', 'downgrade']) as choice}
              <label class="flex items-center gap-1">
                <input type="radio" name={`choice-${keyOf(u)}`} value={choice} bind:group={draft.choice} />
                {wb.CHOICE_LABELS[choice as wb.Choice]}
              </label>
            {/each}
          </fieldset>
          <textarea aria-label="理由" class="w-full border border-border rounded p-2 text-sm bg-bg" rows="2"
                    placeholder="写一句理由（必填）" bind:value={draft.reason}></textarea>
          <div class="flex items-center gap-2">
            <button type="submit" class="text-sm px-3 py-1 rounded bg-accent text-white disabled:opacity-50"
                    disabled={!draft.reason.trim() || draft.busy}>提交决定</button>
            {#if draft.error}<span class="text-xs text-red-600">{draft.error}</span>{/if}
          </div>
        </form>
      {/if}
    </article>
  {/each}
</section>
