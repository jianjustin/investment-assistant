<script lang="ts">
  import { fmtBeijing } from '../format'
  import * as wb from '../workbench'

  // 备注（spec §6.5）：写给自己的日志，不进 Agent 提示词、不触发复查。
  // 提交由上层做（onNote 抛错即失败）；失败时保留正文与 request id，同一内容重试幂等。
  let { notes, onNote }: { notes: wb.PlanNote[]; onNote: (body: string, requestId: string) => Promise<void> } = $props()

  let body = $state('')
  let requestId = $state<string | null>(null)
  let busy = $state(false)
  let error = $state('')

  // 按码位计数，与后端 char_length 一致。
  const chars = $derived([...body.trim()].length)
  const tooLong = $derived(chars > wb.NOTE_MAX_CHARS)

  async function submit(e: Event) {
    e.preventDefault()
    if (busy || chars === 0 || tooLong) return
    busy = true
    error = ''
    requestId ??= wb.newRequestId()
    try {
      await onNote(body.trim(), requestId)
      body = ''
      requestId = null
    } catch (err) {
      error = wb.describeError(err)
    } finally {
      busy = false
    }
  }
</script>

<section aria-label="备注" class="space-y-1 text-sm">
  <p class="font-medium">备注</p>
  {#if notes.length}
    <ul class="text-xs space-y-0.5">
      {#each notes as n (n.id)}
        <li><span class="text-muted">{fmtBeijing(n.created_at)}</span> <span class="whitespace-pre-wrap">{n.body}</span></li>
      {/each}
    </ul>
  {:else}
    <p class="text-xs text-muted">还没有备注</p>
  {/if}
  <form class="space-y-1" onsubmit={submit}>
    <textarea aria-label="备注正文" class="w-full border border-border rounded p-2 text-sm bg-bg" rows="2"
              placeholder="写给自己的备注（1–1000 字）" bind:value={body}></textarea>
    <p class="text-xs text-muted">{wb.NOTE_HINT_TEXT}</p>
    <div class="flex flex-wrap items-center gap-2">
      <button type="submit" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
              disabled={busy || chars === 0 || tooLong}>保存备注</button>
      {#if tooLong}<span class="text-xs text-red-600">备注最多 {wb.NOTE_MAX_CHARS} 字（现在 {chars} 字）</span>{/if}
      {#if error}<span role="alert" class="text-xs text-red-600">{error}</span>{/if}
    </div>
  </form>
</section>
