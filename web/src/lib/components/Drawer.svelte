<script lang="ts">
  let { open = false, onclose, children }: { open: boolean; onclose?: () => void; children?: any } = $props()
</script>
{#if open}
  <div class="fixed inset-0 z-40" role="presentation" onclick={onclose} onkeydown={e => e.key === 'Escape' && onclose?.()}></div>
  <aside class="fixed right-0 top-0 h-full w-96 bg-surface shadow-elev-2 z-50 overflow-y-auto p-4 transition-transform">
    <button class="mb-4 text-muted" onclick={onclose}>✕ 关闭</button>
    {@render children()}
  </aside>
{/if}
