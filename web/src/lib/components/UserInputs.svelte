<script lang="ts">
  import { onMount } from 'svelte'
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
  let error = $state('')
  let notice = $state('')
  let retractIds = $state<Record<number, string>>({})

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

  function validate(): string | null {
    const body = draft.body.trim()
    if (!body) return '正文不能为空'
    // 按码位计数，与后端 char_length 一致（emoji 等补充平面字符算 1 个字）。
    const chars = [...body].length
    if (chars > MAX_BODY) return `正文最多 ${MAX_BODY} 字（现在 ${chars} 字）`
    const url = draft.url.trim()
    if (url && (!/^https?:\/\//i.test(url) || [...url].length > MAX_URL)) return `链接须以 http:// 或 https:// 开头，最多 ${MAX_URL} 字`
    return null
  }

  const scopeOf = (d: Draft): string | undefined =>
    d.supersedes ? (d.supersedes.signal_date ?? undefined) : (signalDate ?? (d.scope || undefined))

  async function submit() {
    if (busy) return
    const invalid = validate()
    if (invalid) { error = invalid; return }
    busy = true
    error = ''
    notice = ''
    const scope = scopeOf(draft)
    const url = draft.url.trim()
    const body: tl.UserInputBody = {
      request_id: draft.requestId, ticker, ...(scope ? { signal_date: scope } : {}), kind: draft.kind,
      body: draft.body.trim(), ...(url ? { source_url: url } : {}),
      ...(draft.supersedes ? { supersedes_id: draft.supersedes.id } : {}),
    }
    try {
      const out = await api.postUserInput(body)
      notice = `已记录 user:${out.record.id}${scope ? '，需要时可以「重新复查」这条链' : ''}`
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
    notice = ''
  }

  async function retract(item: tl.UserInput) {
    const requestId = retractIds[item.id] ??= wb.newRequestId()
    error = ''
    notice = ''
    try {
      const out = await api.postUserInput({
        request_id: requestId, ticker, ...(item.signal_date ? { signal_date: item.signal_date } : {}),
        kind: 'retract', body: `撤回 user:${item.id}`, supersedes_id: item.id,
      })
      delete retractIds[item.id]
      notice = `已撤回 user:${item.id}（记录 user:${out.record.id}）`
      await load()
    } catch (e) {
      error = wb.describeError(e)
    }
  }

  const headline = (item: tl.UserInput) => [
    item.ref ?? `user:${item.id}`, tl.USER_INPUT_KIND_TEXT[item.kind] ?? item.kind, fmtBeijing(item.created_at),
    item.signal_date ? `信号日 ${item.signal_date}` : '整个标的',
    ...(item.status && STATUS_TEXT[item.status] ? [STATUS_TEXT[item.status]] : []),
    ...(item.supersedes_id ? [`指向 user:${item.supersedes_id}`] : []),
  ].join(' · ')
</script>

<section aria-label="我的补充" class="border border-border rounded-sm p-3 bg-card text-sm space-y-2">
  <h2 class="font-semibold">我的补充</h2>
  <p class="text-xs text-muted-foreground">补充只作为证据给 Agent 复查参考，不是指令，不会改变规则、价位口径或校验。</p>

  <form class="space-y-2" onsubmit={e => { e.preventDefault(); void submit() }}>
    {#if draft.supersedes}
      <p class="text-xs text-amber-700">正在更正 {draft.supersedes.ref ?? `user:${draft.supersedes.id}`}
        <button type="button" class="underline" onclick={() => { draft = blank(); error = '' }}>取消</button></p>
    {/if}
    <div class="flex flex-wrap gap-2">
      <label class="flex items-center gap-1 text-xs">类型
        <select aria-label="类型" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={draft.kind}>
          {#each KINDS as k}<option value={k}>{tl.USER_INPUT_KIND_TEXT[k]}</option>{/each}
        </select>
      </label>
      {#if !signalDate && !draft.supersedes}
        <label class="flex items-center gap-1 text-xs">作用于
          <select aria-label="作用于" class="border border-border rounded-sm px-2 py-1 bg-background" bind:value={draft.scope}>
            <option value="">整个标的</option>
            {#each chains as c (c.signal_date)}<option value={c.signal_date}>{c.label}</option>{/each}
          </select>
        </label>
      {/if}
    </div>
    <textarea aria-label="正文" rows="3" class="w-full border border-border rounded-sm p-2 bg-background"
              placeholder="研报要点、新闻或你的判断（1–4000 字）" bind:value={draft.body}></textarea>
    <input aria-label="链接" class="w-full border border-border rounded-sm px-2 py-1 bg-background" placeholder="可选链接（http/https）"
           bind:value={draft.url} />
    <div class="flex items-center gap-2">
      <button type="submit" class="text-sm px-3 py-1 rounded-sm bg-primary text-white disabled:opacity-50" disabled={busy}>提交补充</button>
      {#if error}<span role="alert" class="text-xs text-red-600">{error}</span>{/if}
      {#if notice}<span class="text-xs text-muted-foreground">{notice}</span>{/if}
    </div>
  </form>

  {#if loadError}
    <p class="text-xs text-red-600">{loadError}</p>
  {:else if loading && !inputs.length}
    <p class="text-xs text-muted-foreground">加载中…</p>
  {:else if !inputs.length}
    <p class="text-xs text-muted-foreground">还没有补充</p>
  {:else}
    <ul aria-label="补充列表" class="space-y-2">
      {#each inputs as item (item.id)}
        <li class="border-l-2 border-border pl-2">
          <p class="text-xs text-muted-foreground">{headline(item)}</p>
          <p class="whitespace-pre-wrap wrap-break-word">{item.body}</p>
          {#if item.source_url}<a class="text-xs underline break-all" href={item.source_url} target="_blank" rel="noreferrer">{item.source_url}</a>{/if}
          {#if (item.status ?? 'active') === 'active' && item.kind !== 'retract'}
            <div class="flex gap-2 text-xs">
              <button class="text-primary underline" onclick={() => correct(item)}>更正</button>
              <button class="text-primary underline" onclick={() => retract(item)}>撤回</button>
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>
