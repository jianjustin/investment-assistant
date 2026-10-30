<script module lang="ts">
  let formSeq = 0
</script>

<script lang="ts">
  import { untrack } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import { Textarea } from '$lib/ui/textarea/index'
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
  const uid = $props.id()
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

<div class="grid gap-3 text-sm">
  <Field label="标题" id={`${uid}-title`} required>
    {#snippet children({ id, describedby, invalid })}
      <Input {id} aria-describedby={describedby} aria-invalid={invalid} bind:value={title} />
    {/snippet}
  </Field>
  <Field label="正文" id={`${uid}-body`} required>
    {#snippet children({ id, describedby, invalid })}
      <Textarea {id} rows={4} aria-describedby={describedby} aria-invalid={invalid} bind:value={body} />
    {/snippet}
  </Field>
  <Field label="适用范围" id={`${uid}-scope`} required>
    {#snippet children({ id, describedby, invalid })}
      <Textarea {id} rows={2} aria-describedby={describedby} aria-invalid={invalid} bind:value={scope} />
    {/snippet}
  </Field>
  <Field label="反例" id={`${uid}-counter`} required={requireCounter} hint={requireCounter ? '必填' : '可空'}>
    {#snippet children({ id, describedby, invalid })}
      <Textarea {id} rows={2} aria-describedby={describedby} aria-invalid={invalid} bind:value={counter} />
    {/snippet}
  </Field>

  <div class="grid gap-2">
    <p class="text-xs text-muted-foreground">这条经验挂在哪些概念或标的上（合计 1–10 项）</p>
    <div class="flex flex-wrap items-center gap-2">
      <Input aria-label="概念" list={listId} placeholder="概念 id（可从提示里选）" class="w-56 text-xs"
             bind:value={conceptInput} onkeydown={onEnter(addConcept)} />
      <datalist id={listId}>{#each known as id (id)}<option value={id}></option>{/each}</datalist>
      <Button size="sm" onclick={addConcept}>添加概念</Button>
      <Input aria-label="标的" placeholder="标的，如 NVDA" class="w-40 text-xs"
             bind:value={tickerInput} onkeydown={onEnter(addTicker)} />
      <Button size="sm" onclick={addTicker}>添加标的</Button>
    </div>
    <ul class="flex flex-wrap gap-1 text-xs">
      {#each concepts as id (id)}
        <li class="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5"><code>{id}</code>
          <Button variant="ghost" size="icon" class="size-5" aria-label={`移除概念 ${id}`}
                  onclick={() => concepts = concepts.filter(c => c !== id)}><Icon name="x" /></Button></li>
      {/each}
      {#each tickers as t (t)}
        <li class="inline-flex items-center gap-1 rounded-sm bg-muted px-1.5 py-0.5">{t}
          <Button variant="ghost" size="icon" class="size-5" aria-label={`移除标的 ${t}`}
                  onclick={() => tickers = tickers.filter(x => x !== t)}><Icon name="x" /></Button></li>
      {/each}
    </ul>
  </div>

  {#if error}<Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{error}</AlertDescription></Alert>{/if}
  {#if !hideSubmit}
    <div><Button variant="primary" {busy} onclick={submit}>{submitLabel}</Button></div>
  {/if}
</div>
