<script lang="ts">
  import { cn } from '$lib/utils.js'

  type Item = { href: string; label: string; current: boolean; badge?: string | number; badgeLabel?: string }
  let { label, items }: { label: string; items: Item[] } = $props()
</script>

<!-- Route-level tabs are navigation: links with aria-current, not a tablist. -->
<nav aria-label={label} class="flex gap-1 overflow-x-auto border-b border-border">
  {#each items as item}
    <a
      href={item.href}
      aria-current={item.current ? 'page' : undefined}
      class={cn(
        '-mb-px inline-flex h-8 shrink-0 items-center gap-1.5 border-b-2 px-3 text-sm font-medium transition-colors',
        item.current
          ? 'border-primary text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      {item.label}
      {#if item.badge !== undefined}
        <span aria-label={item.badgeLabel} title={item.badgeLabel} class="rounded-full bg-muted px-1.5 text-xs leading-5 text-foreground">{item.badge}</span>
      {/if}
    </a>
  {/each}
</nav>
