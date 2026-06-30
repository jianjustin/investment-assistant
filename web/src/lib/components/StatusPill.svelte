<script lang="ts">
  let { status }: { status: string } = $props()
  const cls: Record<string, string> = {
    green: 'bg-success/20 text-success',
    yellow: 'bg-warn/20 text-warn',
    red: 'bg-danger/20 text-danger',
    active: 'bg-success/20 text-success',
    error: 'bg-danger/20 text-danger',
    done: 'bg-success/20 text-success',
    success: 'bg-success/20 text-success',
    pending: 'bg-warn/20 text-warn',
  }
</script>
<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {cls[status] ?? 'bg-surface-2 text-muted'}">
  {status}
</span>
