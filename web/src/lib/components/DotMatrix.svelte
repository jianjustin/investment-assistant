<script lang="ts">
  import { STATUS_COLORS, type DayCell } from '../signals'
  let { cells }: { cells: DayCell[] } = $props()
</script>

<div class="flex flex-wrap gap-1" style="max-width:340px">
  {#each cells as c}
    <span
      data-testid="dot"
      title={c.date}
      style="width:15px;height:15px;border-radius:3px;background:{STATUS_COLORS[c.status]}"
    ></span>
  {/each}
</div>
