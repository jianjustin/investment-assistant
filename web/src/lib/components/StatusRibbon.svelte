<script lang="ts">
  import { STATUS_COLORS, type DayCell } from '../signals'
  let { cells }: { cells: DayCell[] } = $props()
</script>

<div class="flex rounded-md overflow-hidden" style="height:34px;width:100%">
  {#each cells as c}
    <span
      data-testid="ribbon-seg"
      title={c.date}
      style="flex:1;height:100%;background:{STATUS_COLORS[c.status]}"
    ></span>
  {/each}
</div>
