<script lang="ts">
  import { cn } from '$lib/utils.js'
  import { ICONS, type IconName } from './icons'

  // Thin wrapper over @lucide/svelte: two sizes only (16 / 20); decorative (aria-hidden) unless `label` is given.
  let { name, size = 16, label, class: className }: { name: IconName; size?: 16 | 20; label?: string; class?: string } = $props()

  const Glyph = $derived(ICONS[name])
</script>

<Glyph
  {size}
  class={cn('shrink-0', size === 20 ? 'size-5' : 'size-4', className)}
  aria-hidden={label ? undefined : 'true'}
  aria-label={label}
  role={label ? 'img' : undefined}
/>
