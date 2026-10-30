<script module lang="ts">
  let formSeq = 0
</script>

<script lang="ts">
  import { untrack } from 'svelte'
  import { conceptIndex } from '../knowledge'
  import {
    conceptId, growthError, idempotentRequests, isTickerLike, knowledgeProblem, normalizeTicker,
  } from '../growth'
  import type { KnowledgeValues, KnowledgeVersion } from '../growth'

  // 「我的知识」的写 / 改表单（spec §5.5）。「我的知识」页、改版、草稿采纳都用它；复盘卡审定把它当字段编辑器用
  // （hideSubmit + onChange，由卡的表单统一提交）。提交带 request_id：同一份内容失败后重试复用同一个，内容变了换新的，
  // 成功后下一次是新的写入。失败保留所有输入。
  let { initial, requireCounter = false, onSubmit, onChange, hideSubmit = false, submitLabel = '提交', requestKey = '' }: {
    initial?: Partial<KnowledgeVersion>; requireCounter?: boolean
    onSubmit?: (values: KnowledgeValues, requestId: string) => Promise<void> | void
    onChange?: (values: KnowledgeValues, problem: string | null) => void
    hideSubmit?: boolean; submitLabel?: string
    /** mixed into the request id key by a parent that adds fields of its own (e.g. base_version) */
    requestKey?: string
  } = $props()

  const seed = untrack(() => initial ?? {})
  const listId = `concept-options-${++formSeq}`
  let title = $state(seed.title ?? '')
  let body = $state(seed.body ?? '')
  let scope = $state(seed.scope ?? '')
  let counter = $state(seed.counter_examples ?? '')
  let concepts = $state<string[]>((seed.concepts ?? []).map(conceptId))
  let tickers = $state<string[]>([...(seed.tickers ?? [])])
  let conceptInput = $state('')
  let tickerInput = $state('')
  let known = $state<string[]>([])
  let error = $state('')
  let busy = $state(false)
  const requests = idempotentRequests()

  conceptIndex().then(index => { known = [...index.keys()].sort() }).catch(() => { known = [] })

  const values = $derived<KnowledgeValues>({
    title: title.trim(), body: body.trim(), scope: scope.trim(), counter_examples: counter.trim(),
    concepts: [...concepts], tickers: [...tickers],
  })
  const problem = $derived(knowledgeProblem(values, { requireCounter }))

  $effect(() => {
    const v = values
    const p = problem
    untrack(() => onChange?.(v, p))
  })

  async function addConcept() {
    const id = conceptId(conceptInput.trim())
    if (!id) return
    if (!/^[a-z]+\.[a-z0-9_]+$/.test(id)) { error = `概念 id 格式不对：${id}`; return }
    // The index may be unavailable (offline card catalog): then only the format is checked.
    const index = await conceptIndex().catch(() => null)
    if (index && !index.has(id)) { error = `没有这张概念卡：${id}`; return }
    if (!concepts.includes(id)) concepts = [...concepts, id]
    conceptInput = ''
    error = ''
  }
  function addTicker() {
    const t = normalizeTicker(tickerInput)
    if (!t) return
    if (!isTickerLike(t)) { error = `标的代码不合法：${tickerInput.trim()}`; return }
    if (!tickers.includes(t)) tickers = [...tickers, t]
    tickerInput = ''
    error = ''
  }
  const onEnter = (action: () => void) => (e: KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); action() }
  }

  async function submit() {
    if (busy) return
    if (problem) { error = problem; return }
    busy = true
    error = ''
    try {
      await onSubmit?.(values, requests.idFor({ values, requestKey }))
      requests.done()
    } catch (e) {
      error = growthError(e)
    } finally {
      busy = false
    }
  }
</script>

<div class="space-y-2 text-sm">
  <label class="flex flex-col">标题
    <input aria-label="标题" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={title} />
  </label>
  <label class="flex flex-col">正文
    <textarea aria-label="正文" rows="4" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={body}></textarea>
  </label>
  <label class="flex flex-col">适用范围
    <textarea aria-label="适用范围" rows="2" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={scope}></textarea>
  </label>
  <label class="flex flex-col">反例{requireCounter ? '（必填）' : '（可空）'}
    <textarea aria-label="反例" rows="2" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={counter}></textarea>
  </label>

  <div class="space-y-1">
    <p class="text-xs text-muted-foreground">这条经验挂在哪些概念或标的上（合计 1–10 项）</p>
    <div class="flex flex-wrap items-center gap-1">
      <input aria-label="概念" list={listId} placeholder="概念 id（可从提示里选）"
             class="border border-border rounded-sm px-2 py-1 bg-background text-xs" bind:value={conceptInput}
             onkeydown={onEnter(addConcept)} />
      <datalist id={listId}>{#each known as id (id)}<option value={id}></option>{/each}</datalist>
      <button type="button" class="text-xs px-2 py-1 border border-border rounded-sm hover:bg-muted" onclick={addConcept}>添加概念</button>
      <input aria-label="标的" placeholder="标的，如 NVDA" class="border border-border rounded-sm px-2 py-1 bg-background text-xs"
             bind:value={tickerInput} onkeydown={onEnter(addTicker)} />
      <button type="button" class="text-xs px-2 py-1 border border-border rounded-sm hover:bg-muted" onclick={addTicker}>添加标的</button>
    </div>
    <ul class="flex flex-wrap gap-1 text-xs">
      {#each concepts as id (id)}
        <li class="px-1.5 py-0.5 rounded-sm bg-muted"><code>{id}</code>
          <button type="button" aria-label={`移除概念 ${id}`} class="text-muted-foreground hover:text-red-600"
                  onclick={() => concepts = concepts.filter(c => c !== id)}>×</button></li>
      {/each}
      {#each tickers as t (t)}
        <li class="px-1.5 py-0.5 rounded-sm bg-muted">{t}
          <button type="button" aria-label={`移除标的 ${t}`} class="text-muted-foreground hover:text-red-600"
                  onclick={() => tickers = tickers.filter(x => x !== t)}>×</button></li>
      {/each}
    </ul>
  </div>

  {#if error}<p role="alert" class="text-xs text-red-600">{error}</p>{/if}
  {#if !hideSubmit}
    <button type="button" class="px-3 py-1 rounded-sm bg-primary text-white disabled:opacity-50" disabled={busy}
            onclick={submit}>{submitLabel}</button>
  {/if}
</div>
