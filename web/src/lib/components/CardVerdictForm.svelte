<script lang="ts">
  import KnowledgeForm from './KnowledgeForm.svelte'
  import RefList from './RefList.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { growthError, idempotentRequests, knowHref } from '../growth'
  import type { CardVerdict, CardVerdictLessonInput, KnowledgeValues, LessonDraftRow, VerdictAction } from '../growth'

  // 复盘卡的审定表单（spec §4.5）：每条教训草稿必须「采纳」（字段可改）或「不采纳」，可以「另写一条」，
  // 可以写「我的复盘」（0–2000 字）；一次提交，审定后不能再审定。失败保留所有输入；同一份内容重试复用 request_id。
  let { cardId, drafts, verdict, runId = null, onFact, onSubmitted }: {
    cardId: number; drafts: LessonDraftRow[]; verdict: CardVerdict | null; runId?: string | null
    onFact?: (key: string) => void; onSubmitted?: () => void
  } = $props()

  type Edit = { values: KnowledgeValues; problem: string | null }
  let choice = $state<Record<number, VerdictAction | undefined>>({})
  let edits = $state<Record<number, Edit | undefined>>({})
  let extras = $state<{ key: number; edit: Edit | null }[]>([])
  let note = $state('')
  let busy = $state(false)
  let error = $state('')
  let nextKey = 1
  const requests = idempotentRequests()

  const unhandled = $derived(drafts.filter(d => !choice[d.id]).length)
  const original = (d: LessonDraftRow): KnowledgeValues => ({
    title: d.title, body: d.body, scope: d.scope, counter_examples: d.counter_examples,
    concepts: [...d.concepts], tickers: [...d.tickers],
  })

  function payload(): { note: string; lessons: CardVerdictLessonInput[] } {
    const lessons: CardVerdictLessonInput[] = drafts.map(d => choice[d.id] === 'approve'
      ? { draft_id: d.id, action: 'approve', ...(edits[d.id]?.values ?? original(d)) }
      : { draft_id: d.id, action: 'dismiss', ...original(d) })
    for (const extra of extras) if (extra.edit) lessons.push({ action: 'approve', ...extra.edit.values })
    return { note: note.trim(), lessons }
  }

  async function submit() {
    if (busy || unhandled > 0) return
    if ([...note.trim()].length > 2000) { error = `我的复盘最多 2000 字（现在 ${[...note.trim()].length} 字）`; return }
    for (const d of drafts) {
      const problem = choice[d.id] === 'approve' ? edits[d.id]?.problem : null
      if (problem) { error = `教训「${d.title}」：${problem}`; return }
    }
    for (const [i, extra] of extras.entries()) {
      const problem = extra.edit ? extra.edit.problem : '标题不能为空'
      if (problem) { error = `另写的教训 ${i + 1}：${problem}`; return }
    }
    busy = true
    error = ''
    const body = payload()
    try {
      await api.postCardVerdict(cardId, { request_id: requests.idFor(body), ...body })
      requests.done()
      onSubmitted?.()
    } catch (e) {
      error = growthError(e)
    } finally {
      busy = false
    }
  }
</script>

{#if verdict}
  <div class="space-y-2 text-sm">
    <p class="text-xs"><span class="font-medium">已审定</span> <span class="text-muted">{fmtBeijing(verdict.created_at)}</span></p>
    {#if verdict.note}
      <div>
        <p class="text-xs text-muted">我的复盘</p>
        <p class="whitespace-pre-wrap">{verdict.note}</p>
      </div>
    {/if}
    <ul class="space-y-0.5 text-xs">
      {#each verdict.lessons as lesson, i (i)}
        <li class={lesson.action === 'dismiss' ? 'text-muted' : ''}>
          <span>{lesson.title}</span>
          {#if lesson.action === 'approve' && lesson.ref}
            → <a class="text-accent underline" href={knowHref(lesson.ref)}>{lesson.ref}</a>
          {:else if lesson.action === 'dismiss'}· 不采纳{/if}
        </li>
      {:else}
        <li class="text-muted">没有教训</li>
      {/each}
    </ul>
  </div>
{:else}
  <div class="space-y-3 text-sm">
    {#each drafts as d, i (d.id)}
      <fieldset aria-label={`教训草稿 ${i + 1}：${d.title}`} class="border border-border rounded p-3 space-y-2 min-w-0">
        <legend class="px-1 text-xs text-muted">教训草稿 {i + 1}</legend>
        <p class="font-medium">{d.title}</p>
        <p class="whitespace-pre-wrap">{d.body}</p>
        <p class="text-xs"><span class="text-muted">适用范围</span> {d.scope}</p>
        <p class="text-xs"><span class="text-muted">反例</span> {d.counter_examples}</p>
        {#if d.refs?.length}<p class="text-xs text-muted">依据<RefList refs={d.refs} {runId} {onFact} /></p>{/if}
        <div class="flex gap-2">
          <button type="button" aria-pressed={choice[d.id] === 'approve'}
                  class="text-xs px-2 py-1 border rounded {choice[d.id] === 'approve' ? 'border-accent bg-accent/10 text-accent' : 'border-border hover:bg-surface-2'}"
                  onclick={() => choice[d.id] = 'approve'}>采纳</button>
          <button type="button" aria-pressed={choice[d.id] === 'dismiss'}
                  class="text-xs px-2 py-1 border rounded {choice[d.id] === 'dismiss' ? 'border-accent bg-accent/10 text-accent' : 'border-border hover:bg-surface-2'}"
                  onclick={() => choice[d.id] = 'dismiss'}>不采纳</button>
        </div>
        {#if choice[d.id] === 'approve'}
          <KnowledgeForm initial={d} requireCounter hideSubmit onChange={(values, problem) => edits[d.id] = { values, problem }} />
        {/if}
      </fieldset>
    {/each}

    {#each extras as extra, i (extra.key)}
      <fieldset aria-label={`另写的教训 ${i + 1}`} class="border border-border rounded p-3 space-y-2 min-w-0">
        <legend class="px-1 text-xs text-muted">另写的教训 {i + 1}</legend>
        <KnowledgeForm hideSubmit onChange={(values, problem) => extra.edit = { values, problem }} />
        <button type="button" class="text-xs px-2 py-1 border border-border rounded"
                onclick={() => extras = extras.filter(x => x.key !== extra.key)}>移除这一条</button>
      </fieldset>
    {/each}
    <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2"
            onclick={() => extras = [...extras, { key: nextKey++, edit: null }]}>另写一条</button>

    <label class="flex flex-col">我的复盘（0–2000 字）
      <textarea aria-label="我的复盘" rows="3" class="border border-border rounded px-2 py-1 bg-bg" bind:value={note}></textarea>
    </label>

    {#if unhandled > 0}<p class="text-xs text-amber-700">还有 {unhandled} 条教训草稿没有处理</p>{/if}
    {#if error}<p role="alert" class="text-xs text-red-600">{error}</p>{/if}
    <div class="flex items-center gap-2">
      <button type="button" class="px-3 py-1 rounded bg-accent text-white disabled:opacity-50"
              disabled={busy || unhandled > 0} onclick={submit}>提交审定</button>
      <span class="text-xs text-muted">审定后不能再审定；之后要改经验，到「我的知识」改版本。</span>
    </div>
  </div>
{/if}
