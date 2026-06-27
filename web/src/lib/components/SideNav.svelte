<script lang="ts">
  import { t } from '../i18n'

  let { current }: { current: string } = $props()
  const zones = ['dashboard', 'market', 'watchlist', 'strategy', 'hermes', 'system'] as const
  const icons: Record<string, string> = {
    dashboard: '⊞', market: '📈', watchlist: '🔍', strategy: '🎯', hermes: '🤖', system: '⚙️'
  }
</script>
<nav class="flex flex-col gap-1 py-4 px-1 bg-surface border-r border-border h-full w-14">
  {#each zones as zone}
    <a
      href="#{zone}"
      aria-label={t(zone)}
      class="flex flex-col items-center gap-0.5 p-2 rounded text-xs transition-colors
        {current === zone ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-surface-2'}"
    >
      <span class="text-lg">{icons[zone]}</span>
    </a>
  {/each}
</nav>
