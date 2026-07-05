<script lang="ts">
  import Modal from './Modal.svelte'
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
  const MODES: [Mode, string][] = [
    ['default', defaultLabel],
    ['single', '指定单日'],
    ['range', '日期范围'],
  ]

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
<Modal {open} {title} {onclose}>
  {#if description}
    <p class="text-xs text-muted mb-3">{description}</p>
  {/if}
  <div class="flex gap-1 mb-4 bg-bg rounded-lg p-1">
    {#each MODES as [m, label]}
      <button
        class="flex-1 px-2 py-1.5 rounded-md text-sm transition-colors {mode === m ? 'bg-accent text-white shadow-elev-1' : 'text-muted hover:bg-accent/10'}"
        onclick={() => (mode = m)}
      >{label}</button>
    {/each}
  </div>
  {#if mode === 'single'}
    <div class="mb-4">
      <label class="block text-xs text-muted mb-1" for="fetch-single-date">日期</label>
      <input id="fetch-single-date" type="date" bind:value={single}
        class="w-full border border-border rounded px-2 py-1.5 text-sm bg-bg" />
    </div>
  {:else if mode === 'range'}
    <div class="grid grid-cols-2 gap-2 mb-1">
      <div>
        <label class="block text-xs text-muted mb-1" for="fetch-range-from">开始</label>
        <input id="fetch-range-from" type="date" bind:value={from}
          class="w-full border border-border rounded px-2 py-1.5 text-sm bg-bg" />
      </div>
      <div>
        <label class="block text-xs text-muted mb-1" for="fetch-range-to">结束</label>
        <input id="fetch-range-to" type="date" bind:value={to}
          class="w-full border border-border rounded px-2 py-1.5 text-sm bg-bg" />
      </div>
    </div>
    <p class="text-[11px] text-muted mb-3">一次最多拉取 {maxRangeDays} 天</p>
  {/if}
  {#if error}
    <p class="text-xs text-red-500 mb-2">{error}</p>
  {/if}
  <div class="flex justify-end gap-2 mt-2">
    <button class="px-3 py-1.5 rounded text-sm text-muted hover:bg-accent/5" onclick={onclose}>取消</button>
    <button
      class="px-4 py-1.5 rounded bg-accent text-white text-sm disabled:opacity-50"
      disabled={!!error}
      onclick={confirm}
    >确认</button>
  </div>
</Modal>
