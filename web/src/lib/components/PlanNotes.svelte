<script lang="ts">
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import Field from '$lib/ui/field/Field.svelte'
  import { Textarea } from '$lib/ui/textarea/index'
  import { notify } from '$lib/ui/toast'
  import { fmtBeijing } from '../format'
  import * as wb from '../workbench'

  // 备注（spec §6.5）：写给自己的日志，不进 Agent 提示词、不触发复查。
  // 提交由上层做（onNote 抛错即失败）；失败时保留正文与 request id，同一内容重试幂等；正文改过就换新的 request id。
  let { notes, onNote }: { notes: wb.PlanNote[]; onNote: (body: string, requestId: string) => Promise<void> } = $props()

  let body = $state('')
  let requestId = $state<string | null>(null)
  let busy = $state(false)
  let error = $state('')
  const uid = $props.id()

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
      notify.success('备注已保存')
    } catch (err) {
      error = wb.describeError(err)
    } finally {
      busy = false
    }
  }
</script>

<section aria-label="备注" class="grid gap-2 text-sm">
  <p class="font-medium">备注</p>
  {#if notes.length}
    <ul class="grid gap-0.5 text-xs">
      {#each notes as n (n.id)}
        <li><span class="text-muted-foreground">{fmtBeijing(n.created_at)}</span> <span class="whitespace-pre-wrap">{n.body}</span></li>
      {/each}
    </ul>
  {:else}
    <p class="text-xs text-muted-foreground">还没有备注</p>
  {/if}
  <form class="grid gap-2" onsubmit={submit}>
    <Field label="备注正文" id={`${uid}-body`} hint={wb.NOTE_HINT_TEXT}
           error={tooLong ? `备注最多 ${wb.NOTE_MAX_CHARS} 字（现在 ${chars} 字）` : null}>
      {#snippet children({ id, describedby, invalid })}
        <Textarea {id} rows={2} aria-describedby={describedby} aria-invalid={invalid} readonly={busy}
                  placeholder="写给自己的备注（1–1000 字）" bind:value={body} oninput={() => { requestId = null }} />
      {/snippet}
    </Field>
    {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}
    <div><Button type="submit" size="sm" {busy} disabled={chars === 0 || tooLong}>保存备注</Button></div>
  </form>
</section>
