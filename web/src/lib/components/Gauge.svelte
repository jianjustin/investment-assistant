<script lang="ts">
  let { judgement }: { judgement: string } = $props()
  const MAP: Record<string, { label: string; color: string; arc: string }> = {
    risk_off: { label: '偏空', color: '#ef4444', arc: 'M10 65 A50 50 0 0 1 45 22' },
    neutral: { label: '中性', color: '#eab308', arc: 'M10 65 A50 50 0 0 1 92 30' },
    risk_on: { label: '偏积极', color: '#22c55e', arc: 'M10 65 A50 50 0 0 1 92 30' },
  }
  let m = $derived(MAP[judgement] ?? MAP.neutral)
</script>

<svg data-testid="gauge" width="120" height="72" viewBox="0 0 120 72">
  <path d="M10 65 A50 50 0 0 1 110 65" fill="none" stroke="#2a2a2a" stroke-width="10" stroke-linecap="round" />
  <path d={m.arc} fill="none" stroke={m.color} stroke-width="10" stroke-linecap="round" />
  <text x="60" y="60" text-anchor="middle" fill={m.color} font-size="13" font-weight="700">{m.label}</text>
</svg>
