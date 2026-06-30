<script lang="ts">
  let { title, note, planned }: { title: string; note: string; planned?: string } = $props()
</script>

<section class="max-w-xl">
  <h2 class="text-lg font-semibold text-ink mb-2">{title}</h2>
  <p class="text-sm text-muted mb-3">{note}</p>
  {#if planned}
    <p class="text-xs text-muted border border-border rounded px-3 py-2 bg-surface-2">🚧 {planned}</p>
  {/if}
</section>
