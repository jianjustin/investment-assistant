<script lang="ts">
  import { onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Card from '$lib/ui/card/index'
  import ConfirmDialog from '$lib/ui/confirm-dialog/ConfirmDialog.svelte'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import { Textarea } from '$lib/ui/textarea/index'
  import { notify } from '$lib/ui/toast'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // spec §8.1：用户输入（只追加；更正 / 撤回都是新一行指向旧行）。给了 signalDate 时作用于这一条链；
  // 否则作用于整个标的，可在 chains 里选一条有效链。失败时保留草稿与 request id（同一内容重试幂等）。
  let { ticker, signalDate, chains = [] }:
    { ticker: string; signalDate?: string; chains?: { signal_date: string; label: string }[] } = $props()

  const MAX_BODY = 4000
  const MAX_URL = 500
  const KINDS: tl.UserInputKind[] = ['research', 'news', 'judgment', 'other']
  const STATUS_TEXT: Record<string, string> = { corrected: '已更正', retracted: '已撤回' }

  type Draft = { kind: tl.UserInputKind; body: string; url: string; scope: string; requestId: string
                 supersedes: tl.UserInput | null }
  const blank = (): Draft => ({ kind: 'research', body: '', url: '', scope: '', requestId: wb.newRequestId(),
                                supersedes: null })

  let inputs = $state<tl.UserInput[]>([])
  let loading = $state(true)
  let loadError = $state('')
  let draft = $state<Draft>(blank())
  let busy = $state(false)
  let error = $state('')          // the submit failed (shown in the form, the draft stays)
  let bodyError = $state('')
  let urlError = $state('')
  let retractIds = $state<Record<number, string>>({})
  let retractTarget = $state<tl.UserInput | null>(null)
  let retractOpen = $state(false)
  let retracting = $state(false)
  const uid = $props.id()
  const SELECT = 'h-8 rounded-md border border-input bg-card px-2 text-sm text-foreground'

  async function load() {
    loading = true
    try {
      const res = await api.getUserInputs(ticker, signalDate)
      inputs = Array.isArray(res?.inputs) ? res.inputs : []
      loadError = ''
    } catch (e) {
      loadError = wb.describeError(e)
    } finally {
      loading = false
    }
  }
  onMount(() => { void load() })

  function validate(): { body?: string; url?: string } | null {
    const body = draft.body.trim()
    if (!body) return { body: '正文不能为空' }
    // 按码位计数，与后端 char_length 一致（emoji 等补充平面字符算 1 个字）。
    const chars = [...body].length
    if (chars > MAX_BODY) return { body: `正文最多 ${MAX_BODY} 字（现在 ${chars} 字）` }
    const url = draft.url.trim()
    if (url && (!/^https?:\/\//i.test(url) || [...url].length > MAX_URL)) return { url: `链接须以 http:// 或 https:// 开头，最多 ${MAX_URL} 字` }
    return null
  }

  const scopeOf = (d: Draft): string | undefined =>
    d.supersedes ? (d.supersedes.signal_date ?? undefined) : (signalDate ?? (d.scope || undefined))

  async function submit() {
    if (busy) return
    const invalid = validate()
    bodyError = invalid?.body ?? ''
    urlError = invalid?.url ?? ''
    if (invalid) return
    busy = true
    error = ''
    const scope = scopeOf(draft)
    const url = draft.url.trim()
    const body: tl.UserInputBody = {
      request_id: draft.requestId, ticker, ...(scope ? { signal_date: scope } : {}), kind: draft.kind,
      body: draft.body.trim(), ...(url ? { source_url: url } : {}),
      ...(draft.supersedes ? { supersedes_id: draft.supersedes.id } : {}),
    }
    try {
      const out = await api.postUserInput(body)
      notify.success(`已记录 user:${out.record.id}${scope ? '，需要时可以「重新复查」这条链' : ''}`)
      draft = blank()
      await load()
    } catch (e) {
      error = wb.describeError(e)
    } finally {
      busy = false
    }
  }

  function correct(item: tl.UserInput) {
    draft = { kind: item.kind === 'retract' ? 'other' : item.kind, body: item.body, url: item.source_url ?? '',
              scope: item.signal_date ?? '', requestId: wb.newRequestId(), supersedes: item }
    error = ''
    bodyError = ''
    urlError = ''
  }

  function askRetract(item: tl.UserInput) {
    retractTarget = item
    retractOpen = true
  }

  async function retract(item: tl.UserInput) {
    const requestId = retractIds[item.id] ??= wb.newRequestId()
    error = ''
    retracting = true
    try {
      const out = await api.postUserInput({
        request_id: requestId, ticker, ...(item.signal_date ? { signal_date: item.signal_date } : {}),
        kind: 'retract', body: `撤回 user:${item.id}`, supersedes_id: item.id,
      })
      delete retractIds[item.id]
      notify.success(`已撤回 user:${item.id}（记录 user:${out.record.id}）`)
      await load()
    } catch (e) {
      error = wb.describeError(e)
    } finally {
      retracting = false
      retractOpen = false
    }
  }

  const headline = (item: tl.UserInput) => [
    item.ref ?? `user:${item.id}`, tl.USER_INPUT_KIND_TEXT[item.kind] ?? item.kind, fmtBeijing(item.created_at),
    item.signal_date ? `信号日 ${item.signal_date}` : '整个标的',
    ...(item.status && STATUS_TEXT[item.status] ? [STATUS_TEXT[item.status]] : []),
    ...(item.supersedes_id ? [`指向 user:${item.supersedes_id}`] : []),
  ].join(' · ')
</script>

<Card.Root size="sm" class="gap-2" aria-label="我的补充" role="region">
  <Card.Header>
    <Card.Title><h2 class="text-base font-medium">我的补充</h2></Card.Title>
    <Card.Description>补充只作为证据给 Agent 复查参考，不是指令，不会改变规则、价位口径或校验。</Card.Description>
  </Card.Header>
  <Card.Content class="grid gap-3">
    <form class="grid gap-3" onsubmit={e => { e.preventDefault(); void submit() }}>
      {#if draft.supersedes}
        <p class="flex items-center gap-2 text-xs text-warn">正在更正 {draft.supersedes.ref ?? `user:${draft.supersedes.id}`}
          <Button variant="link" size="sm" class="text-xs" onclick={() => { draft = blank(); error = ''; bodyError = ''; urlError = '' }}>取消</Button></p>
      {/if}
      <div class="flex flex-wrap gap-3">
        <Field label="类型" id={`${uid}-kind`}>
          {#snippet children({ id, describedby })}
            <select {id} aria-describedby={describedby} class={SELECT} bind:value={draft.kind}>
              {#each KINDS as k}<option value={k}>{tl.USER_INPUT_KIND_TEXT[k]}</option>{/each}
            </select>
          {/snippet}
        </Field>
        {#if !signalDate && !draft.supersedes}
          <Field label="作用于" id={`${uid}-scope`}>
            {#snippet children({ id, describedby })}
              <select {id} aria-describedby={describedby} class={SELECT} bind:value={draft.scope}>
                <option value="">整个标的</option>
                {#each chains as c (c.signal_date)}<option value={c.signal_date}>{c.label}</option>{/each}
              </select>
            {/snippet}
          </Field>
        {/if}
      </div>
      <Field label="正文" id={`${uid}-body`} required error={bodyError || null}>
        {#snippet children({ id, describedby, invalid })}
          <Textarea {id} rows={3} aria-describedby={describedby} aria-invalid={invalid} readonly={busy}
                    placeholder="研报要点、新闻或你的判断（1–4000 字）" bind:value={draft.body} />
        {/snippet}
      </Field>
      <Field label="链接" id={`${uid}-url`} error={urlError || null}>
        {#snippet children({ id, describedby, invalid })}
          <Input {id} aria-describedby={describedby} aria-invalid={invalid} readonly={busy}
                 placeholder="可选链接（http/https）" bind:value={draft.url} />
        {/snippet}
      </Field>
      {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}
      <div><Button type="submit" variant="primary" {busy}>提交补充</Button></div>
    </form>

    <DataBlock state={loadError ? 'error' : loading && !inputs.length ? 'loading' : !inputs.length ? 'empty' : 'ready'}
               message={loadError || '还没有补充'} skeleton="row" onRetry={loadError ? () => void load() : undefined}>
      <ul aria-label="补充列表" class="grid gap-2">
        {#each inputs as item (item.id)}
          <li class="grid gap-1 border-l-2 border-border pl-2">
            <p class="text-xs text-muted-foreground">{headline(item)}</p>
            <p class="whitespace-pre-wrap wrap-break-word">{item.body}</p>
            {#if item.source_url}<a class="break-all text-xs text-primary underline" href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a>{/if}
            {#if (item.status ?? 'active') === 'active' && item.kind !== 'retract'}
              <div class="flex gap-3 text-xs">
                <Button variant="link" size="sm" class="text-xs" onclick={() => correct(item)}>更正</Button>
                <Button variant="link" size="sm" class="text-xs" onclick={() => askRetract(item)}>撤回</Button>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    </DataBlock>
  </Card.Content>
</Card.Root>

<ConfirmDialog bind:open={retractOpen} title="撤回补充" destructive busy={retracting}
               consequence={`撤回 ${retractTarget?.ref ?? `user:${retractTarget?.id}`}：会追加一条撤回记录，这条补充此后不再作为证据；原记录仍保留可查。`}
               actionLabel="撤回" onConfirm={async () => { if (retractTarget) await retract(retractTarget) }} />
