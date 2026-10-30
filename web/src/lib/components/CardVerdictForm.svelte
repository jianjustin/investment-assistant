<script lang="ts">
  import KnowledgeForm from './KnowledgeForm.svelte'
  import RefList from './RefList.svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { growthError, idempotentRequests, knowHref } from '../growth'
  import type { CardVerdict, CardVerdictLessonInput, KnowledgeValues, LessonDraftRow, VerdictAction } from '../growth'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import Field from '$lib/ui/field/Field.svelte'
  import { Textarea } from '$lib/ui/textarea/index'
  import { notify } from '$lib/ui/toast'

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
  const uid = $props.id()
  // the chosen answer is shown as pressed (a primary button per draft would break "at most one primary per section")
  const PICKED = 'border-primary bg-primary/10 text-primary hover:bg-primary/10'

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
      notify.success('已提交审定')
      onSubmitted?.()
    } catch (e) {
      error = growthError(e)
    } finally {
      busy = false
    }
  }
</script>

{#if verdict}
  <div class="grid gap-2 text-sm">
    <p class="text-xs"><span class="font-medium">已审定</span> <span class="text-muted-foreground">{fmtBeijing(verdict.created_at)}</span></p>
    {#if verdict.note}
      <div>
        <p class="text-xs text-muted-foreground">我的复盘</p>
        <p class="whitespace-pre-wrap">{verdict.note}</p>
      </div>
    {/if}
    <ul class="grid gap-0.5 text-xs">
      {#each verdict.lessons as lesson, i (i)}
        <li class={lesson.action === 'dismiss' ? 'text-muted-foreground' : ''}>
          <span>{lesson.title}</span>
          {#if lesson.action === 'approve' && lesson.ref}
            → <a class="text-primary underline" href={knowHref(lesson.ref)}>{lesson.ref}</a>
          {:else if lesson.action === 'dismiss'}· 不采纳{/if}
        </li>
      {:else}
        <li class="text-muted-foreground">没有教训</li>
      {/each}
    </ul>
  </div>
{:else}
  <div class="grid gap-3 text-sm">
    {#each drafts as d, i (d.id)}
      <fieldset aria-label={`教训草稿 ${i + 1}：${d.title}`} class="grid min-w-0 gap-2 rounded-md border border-border p-3">
        <legend class="px-1 text-xs text-muted-foreground">教训草稿 {i + 1}</legend>
        <p class="font-medium">{d.title}</p>
        <p class="whitespace-pre-wrap">{d.body}</p>
        <p class="text-xs"><span class="text-muted-foreground">适用范围</span> {d.scope}</p>
        <p class="text-xs"><span class="text-muted-foreground">反例</span> {d.counter_examples}</p>
        {#if d.refs?.length}<p class="text-xs text-muted-foreground">依据<RefList refs={d.refs} {runId} {onFact} /></p>{/if}
        <div class="flex gap-2">
          <Button size="sm" aria-pressed={choice[d.id] === 'approve'} class={choice[d.id] === 'approve' ? PICKED : ''}
                  onclick={() => choice[d.id] = 'approve'}>采纳</Button>
          <Button size="sm" aria-pressed={choice[d.id] === 'dismiss'} class={choice[d.id] === 'dismiss' ? PICKED : ''}
                  onclick={() => choice[d.id] = 'dismiss'}>不采纳</Button>
        </div>
        {#if choice[d.id] === 'approve'}
          <KnowledgeForm initial={d} requireCounter hideSubmit onChange={(values, problem) => edits[d.id] = { values, problem }} />
        {/if}
      </fieldset>
    {/each}

    {#each extras as extra, i (extra.key)}
      <fieldset aria-label={`另写的教训 ${i + 1}`} class="grid min-w-0 gap-2 rounded-md border border-border p-3">
        <legend class="px-1 text-xs text-muted-foreground">另写的教训 {i + 1}</legend>
        <KnowledgeForm hideSubmit onChange={(values, problem) => extra.edit = { values, problem }} />
        <div><Button size="sm" onclick={() => extras = extras.filter(x => x.key !== extra.key)}>移除这一条</Button></div>
      </fieldset>
    {/each}
    <div><Button size="sm" onclick={() => extras = [...extras, { key: nextKey++, edit: null }]}>另写一条</Button></div>

    <Field label="我的复盘（0–2000 字）" id={`${uid}-note`}>
      {#snippet children({ id, describedby })}
        <Textarea {id} aria-describedby={describedby} aria-label="我的复盘" rows={3} bind:value={note} />
      {/snippet}
    </Field>

    {#if unhandled > 0}<p class="text-xs text-warn">还有 {unhandled} 条教训草稿没有处理</p>{/if}
    {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}
    <div class="flex items-center gap-2">
      <Button variant="primary" {busy} disabled={unhandled > 0} onclick={submit}>提交审定</Button>
      <span class="text-xs text-muted-foreground">审定后不能再审定；之后要改经验，到「我的知识」改版本。</span>
    </div>
  </div>
{/if}
