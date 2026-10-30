<script lang="ts">
  import { Badge } from '$lib/ui/badge/index'
  import { cn } from '$lib/utils.js'

  // Where a number came from and whether it is the backup source (reserved for v2.11: defined and in the gallery,
  // not wired to any page yet). The backup flag is a word as well as a tint.
  let { source, fallback = false }: { source: string; fallback?: boolean } = $props()
</script>

<Badge data-source={source} data-fallback={fallback ? 'true' : undefined} class={cn('gap-1.5 font-mono', fallback && 'border-warn/40 bg-warn/10')}>
  {source}
  {#if fallback}<span class="font-sans text-muted-foreground">备源</span>{/if}
</Badge>
