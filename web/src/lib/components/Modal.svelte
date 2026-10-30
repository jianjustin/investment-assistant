<script lang="ts">
  let { open = false, title = '', onclose, children }: {
    open: boolean
    title?: string
    onclose?: () => void
    children?: any
  } = $props()
</script>
{#if open}
  <div
    class="fixed inset-0 z-40 bg-black/30"
    role="presentation"
    onclick={onclose}
    onkeydown={(e) => e.key === 'Escape' && onclose?.()}
  ></div>
  <div
    class="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-104 max-w-[calc(100vw-2rem)] bg-card rounded-xl shadow-2 p-5"
    role="dialog"
    aria-modal="true"
  >
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-semibold text-base">{title}</h3>
      <button class="text-muted-foreground hover:text-primary transition-colors" onclick={onclose} aria-label="关闭">✕</button>
    </div>
    {@render children?.()}
  </div>
{/if}
