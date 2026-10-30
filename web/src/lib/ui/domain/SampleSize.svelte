<script lang="ts">
  import StatusPill from './StatusPill.svelte'

  // `n = 12`; under the threshold it says 样本不足 (no mean without a sample size, v2.7 rule). null = not computed.
  let { n, min = 5 }: { n: number | null; min?: number } = $props()
</script>

{#if n === null || n === undefined}
  <StatusPill domain="block" value="not_computed" />
{:else}
  <span class="inline-flex items-center gap-1.5"><span class="tabular-nums">n = {n}</span>{#if n < min}<StatusPill domain="block" value="insufficient" />{/if}</span>
{/if}
