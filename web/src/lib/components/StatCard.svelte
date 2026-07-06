<script lang="ts">
  let { label, value, tone = 'flat' }: { label: string; value: string; tone?: 'up' | 'down' | 'flat' } = $props()
  const COLOR = { up: '#22c55e', down: '#ef4444', flat: 'inherit' }
</script>

<div data-testid="stat-card" class="border border-border rounded-lg p-3">
  <div class="text-xs text-muted uppercase">{label}</div>
  <b class="text-lg block mt-1" style="color:{COLOR[tone]}">{value}</b>
</div>
