<script lang="ts">
  import { toggleTheme } from '../theme'
  import SideNav from './SideNav.svelte'
  import { createEventStream } from '../sse'

  let { route, sub, children }: { route: string; sub?: string; children?: any } = $props()
  const events = createEventStream('/api/events')
  let lastEvent = $state<string | null>(null)
  $effect(() => {
    const ev = $events
    if (ev) lastEvent = `${ev.kind ?? ev.status} — ${ev.run_id?.slice(0, 8)}`
  })
</script>

<div class="flex h-screen overflow-hidden bg-bg text-ink">
  <SideNav current={route} {sub} />
  <div class="flex flex-col flex-1 min-w-0">
    <header class="flex items-center justify-between px-4 py-2 border-b border-border bg-surface shadow-elev-1">
      <span class="font-semibold text-accent">Hermes</span>
      <div class="flex items-center gap-3 text-sm text-muted">
        {#if lastEvent}<span class="text-xs">🔔 {lastEvent}</span>{/if}
        <button onclick={toggleTheme} class="hover:text-ink transition-colors">⏾ 主题</button>
      </div>
    </header>
    <main class="flex-1 overflow-y-auto p-4">
      {#if children}
        {@render children()}
      {/if}
    </main>
  </div>
</div>
