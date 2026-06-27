<script lang="ts">
  let { height = 'h-24', rows = 1 }: { height?: string; rows?: number } = $props()
</script>
{#each Array(rows) as _, i}
<div class="animate-pulse bg-surface-2 rounded {height} w-full mb-2" role="status" aria-label="loading"></div>
{/each}
