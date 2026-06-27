<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import { createEventStream } from '../lib/sse'

  let macroData = $state<any>(null)
  let signalsTrend = $state<any>(null)
  let loading = $state(true)

  const events = createEventStream('/api/events')
  $effect(() => { if ($events?.kind === 'macro-llm') loadData() })

  async function loadData() {
    loading = true
    try {
      ;[macroData, signalsTrend] = await Promise.all([
        api.getMacroAnalysis(),
        api.getMarketSignalsTrend(),
      ])
    } finally { loading = false }
  }

  onMount(loadData)
</script>

<div>
  <h2 class="text-lg font-semibold mb-4">总览</h2>
  {#if loading}
    <Skeleton rows={3} />
  {:else}
    {#if macroData}
      <div class="bg-surface rounded-lg p-4 mb-4 shadow-elev-1">
        <div class="flex items-center gap-3">
          <span class="text-3xl">{(macroData as any).macro_state === 'offense' ? '🟢' : (macroData as any).macro_state === 'defense' ? '🔴' : '🟡'}</span>
          <div>
            <div class="font-semibold">{(macroData as any).stance_label ?? '—'}</div>
            <div class="text-sm text-muted">{(macroData as any).summary?.slice(0, 80) ?? '—'}</div>
          </div>
        </div>
      </div>
    {/if}
    {#if signalsTrend}
      <div class="grid grid-cols-3 gap-3 mb-4">
        {#each [['green', '绿灯'], ['yellow', '黄灯'], ['red', '红灯']] as [k, label]}
          <div class="bg-surface rounded p-3 text-center shadow-elev-1">
            <div class="text-2xl font-bold tabular">{(signalsTrend as any).status_counts?.[k] ?? 0}</div>
            <div class="text-xs text-muted mt-1">{label}</div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
