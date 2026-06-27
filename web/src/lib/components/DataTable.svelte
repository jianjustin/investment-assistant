<script lang="ts">
  let { rows = [], columns = [] }: {
    rows: Record<string, unknown>[]
    columns: { key: string; label: string }[]
  } = $props()
</script>
<div class="overflow-x-auto">
  <table class="w-full text-sm">
    <thead class="sticky top-0 bg-surface border-b border-border">
      <tr>
        {#each columns as col}
          <th class="px-3 py-2 text-left font-medium text-muted">{col.label}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i}
        <tr class="{i % 2 === 0 ? 'bg-surface' : 'bg-surface-2'} hover:bg-accent/5 transition-colors">
          {#each columns as col}
            <td class="px-3 py-2 tabular">{row[col.key] ?? '—'}</td>
          {/each}
        </tr>
      {/each}
      {#if rows.length === 0}
        <tr><td colspan={columns.length} class="px-3 py-6 text-center text-muted">暂无数据</td></tr>
      {/if}
    </tbody>
  </table>
</div>
