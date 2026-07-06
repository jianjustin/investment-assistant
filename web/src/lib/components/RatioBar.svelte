<script lang="ts">
  import { STATUS_COLORS } from '../signals'
  let { counts }: { counts: { green: number; yellow: number; red: number } } = $props()
  const order = ['green', 'yellow', 'red'] as const
  let total = $derived(Math.max(counts.green + counts.yellow + counts.red, 1))
</script>

<div class="flex rounded-full overflow-hidden" style="height:14px;width:220px">
  {#each order as k}
    <span
      data-testid="ratio-seg"
      style="flex:{counts[k]};min-width:0;background:{STATUS_COLORS[k]}"
      title={`${k} ${counts[k]} (${Math.round((counts[k] / total) * 100)}%)`}
    ></span>
  {/each}
</div>
