<script lang="ts">
  import type { Bar } from '../api'
  let { bars, days = 60 }: { bars: Bar[]; days?: number } = $props()
  let shown = $derived(bars.slice(-days))
  let avg20 = $derived(
    bars.slice(-20).reduce((s, b) => s + b.volume, 0) / Math.max(Math.min(20, bars.length), 1),
  )
  let maxVol = $derived(Math.max(...shown.map((b) => b.volume), 1))
  const W = 460
  const H = 46
</script>

<svg width="100%" height={H} viewBox="0 0 {W} {H}" preserveAspectRatio="none">
  {#each shown as b, i}
    {@const h = (b.volume / maxVol) * H}
    <rect
      data-testid="vol-bar"
      x={(i / shown.length) * W}
      y={H - h}
      width={Math.max(W / shown.length - 1, 1)}
      height={h}
      fill={b.volume >= 1.5 * avg20 ? '#22c55e' : '#3a3a3a'}
    />
  {/each}
</svg>
