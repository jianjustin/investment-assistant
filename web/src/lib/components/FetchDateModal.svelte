<script lang="ts">
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as Dialog from '$lib/ui/dialog/index'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import { Input } from '$lib/ui/input/index'
  import { todayLocalISO } from '../format'

  let {
    open = false,
    title,
    description = '',
    defaultLabel = '今日',
    defaultPayload = {},
    maxRangeDays = 30,
    onConfirm,
    onclose,
  }: {
    open: boolean
    title: string
    description?: string
    defaultLabel?: string
    defaultPayload?: Record<string, string>
    maxRangeDays?: number
    onConfirm: (payload: Record<string, string>) => void
    onclose: () => void
  } = $props()

  type Mode = 'default' | 'single' | 'range'
  const MODES = $derived<[Mode, string][]>([
    ['default', defaultLabel],
    ['single', '指定单日'],
    ['range', '日期范围'],
  ])

  let mode = $state<Mode>('default')
  let single = $state(todayLocalISO())
  let from = $state(todayLocalISO())
  let to = $state(todayLocalISO())

  const error = $derived.by(() => {
    if (mode === 'single' && !single) return '请选择日期'
    if (mode === 'range') {
      if (!from || !to) return '请选择起止日期'
      const days = (new Date(to).getTime() - new Date(from).getTime()) / 86_400_000
      if (days < 0) return '结束日期不能早于开始日期'
      if (days > maxRangeDays) return `超出上限：一次最多拉取 ${maxRangeDays} 天`
    }
    return ''
  })

  function confirm() {
    if (error) return
    if (mode === 'default') onConfirm(defaultPayload)
    else if (mode === 'single') onConfirm({ date: single })
    else onConfirm({ from, to })
  }
</script>
<Dialog.Root {open} onOpenChange={(next) => { if (!next) onclose() }}>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>{title}</Dialog.Title>
      {#if description}<Dialog.Description>{description}</Dialog.Description>{/if}
    </Dialog.Header>
    <div role="group" aria-label="拉取范围" class="flex gap-1 rounded-md bg-muted p-1">
      {#each MODES as [m, label]}
        <Button variant={mode === m ? 'outline' : 'ghost'} aria-pressed={mode === m} class="flex-1"
                onclick={() => (mode = m)}>{label}</Button>
      {/each}
    </div>
    {#if mode === 'single'}
      <Field label="日期" id="fetch-single-date">
        {#snippet children({ id })}<Input {id} type="date" bind:value={single} />{/snippet}
      </Field>
    {:else if mode === 'range'}
      <div class="grid grid-cols-2 gap-2">
        <Field label="开始" id="fetch-range-from">
          {#snippet children({ id })}<Input {id} type="date" bind:value={from} />{/snippet}
        </Field>
        <Field label="结束" id="fetch-range-to">
          {#snippet children({ id })}<Input {id} type="date" bind:value={to} />{/snippet}
        </Field>
      </div>
      <p class="text-xs text-muted-foreground">一次最多拉取 {maxRangeDays} 天</p>
    {/if}
    {#if error}
      <Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{error}</AlertDescription></Alert>
    {/if}
    <Dialog.Footer>
      <Button onclick={onclose}>取消</Button>
      <Button variant="primary" disabled={!!error} onclick={confirm}>确认</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
