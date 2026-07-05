<script lang="ts">
  import type { Snippet } from 'svelte'
  let { rows = [], columns = [], actions }: {
    rows: Record<string, unknown>[]
    columns: { key: string; label: string }[]
    actions?: Snippet<[Record<string, unknown>]>
  } = $props()
</script>
<div class="overflow-x-auto">
  <table class="w-full text-sm">
    <thead class="sticky top-0 bg-surface border-b border-border">
      <tr>
        {#each columns as col}
          <th class="px-3 py-2 text-left font-medium text-muted">{col.label}</th>
        {/each}
        {#if actions}
          <th class="px-3 py-2 text-right font-medium text-muted">操作</th>
        {/if}
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i}
        <tr class="{i % 2 === 0 ? 'bg-surface' : 'bg-surface-2'} hover:bg-accent/5 transition-colors">
          {#each columns as col}
            <td class="px-3 py-2 tabular">{row[col.key] ?? '—'}</td>
          {/each}
          {#if actions}
            <td class="px-3 py-2 text-right">{@render actions(row)}</td>
          {/if}
        </tr>
      {/each}
      {#if rows.length === 0}
        <tr><td colspan={columns.length + (actions ? 1 : 0)} class="px-3 py-6 text-center text-muted">暂无数据</td></tr>
      {/if}
    </tbody>
  </table>
</div>
