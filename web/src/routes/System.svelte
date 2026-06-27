<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'

  let status = $state<any>(null)
  let ops = $state<any[]>([])
  let loading = $state(true)

  async function load() {
    loading = true
    try {
      ;[status, ops] = await Promise.all([
        api.getStatus(),
        api.getOperations().then((r: any) => r.operations ?? []),
      ])
    } finally { loading = false }
  }

  onMount(load)
</script>

<div>
  <h2 class="text-lg font-semibold mb-4">系统</h2>
  {#if loading}
    <Skeleton rows={3} />
  {:else}
    {#if status}
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {#each Object.entries(status as any) as [k, v]}
          {#if typeof v === 'object' && v !== null && 'status' in v}
            <div class="bg-surface rounded p-3 shadow-elev-1">
              <div class="text-xs text-muted mb-1">{k}</div>
              <StatusPill status={(v as any).status ?? 'unknown'} />
            </div>
          {/if}
        {/each}
      </div>
    {/if}
    {#if ops.length > 0}
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <div class="px-4 py-2 border-b border-border text-sm font-medium">最近操作</div>
        <ul class="divide-y divide-border text-sm">
          {#each ops.slice(0, 20) as op}
            <li class="flex justify-between px-4 py-2">
              <span class="text-muted">{(op as any).type} — {(op as any).run_id?.slice(0, 12) ?? '—'}</span>
              <StatusPill status={(op as any).status ?? 'unknown'} />
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/if}
</div>
