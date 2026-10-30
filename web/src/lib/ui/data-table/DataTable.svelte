<script lang="ts" generics="T">
  import type { Snippet } from 'svelte'
  import ChevronRightIcon from '@lucide/svelte/icons/chevron-right'
  import * as Table from '$lib/ui/table/index.js'
  import { Button } from '$lib/ui/button/index.js'
  import { cn } from '$lib/utils.js'
  import { useNarrow } from '$lib/ui/narrow.svelte'
  import type { Column, HeaderGroup, RowGroup } from './types.js'

  let {
    columns,
    rows = [],
    groups,
    rowKey,
    caption,
    headerGroups,
    expandable,
    expanded = $bindable(new Set<string | number>()),
    muted,
    cards = 'never',
    pageSize = 50,
    sticky = true,
  }: {
    columns: Column<T>[]
    rows?: T[]
    groups?: RowGroup<T>[]
    rowKey: (row: T) => string | number
    caption?: string
    headerGroups?: HeaderGroup[]
    expandable?: Snippet<[T]>
    expanded?: Set<string | number>
    muted?: (row: T) => boolean
    cards?: 'never' | 'narrow'
    pageSize?: number
    sticky?: boolean
  } = $props()

  const uid = $props.id()
  const narrow = useNarrow()
  const asCards = $derived(cards === 'narrow' && narrow.current)

  type Section = { key: string; label?: string; rows: T[]; muted: boolean; group?: RowGroup<T> }
  const sections = $derived<Section[]>(
    groups
      ? groups.map((g) => ({ key: g.key, label: g.label, rows: g.rows, muted: !!g.muted, group: g }))
      : [{ key: '', rows, muted: false }],
  )

  // Collapsible groups: `group.open` is the initial state, the user's clicks win afterwards.
  let groupOpen = $state<Record<string, boolean>>({})
  const isOpen = (s: Section) => !s.group?.collapsible || (groupOpen[s.key] ?? s.group.open ?? true)
  function toggleGroup(s: Section) {
    const next = !isOpen(s)
    groupOpen[s.key] = next
    s.group?.onToggle?.(next)
  }

  // Paging: show `pageSize` rows across the open sections, "show more" adds another page.
  let extra = $state(0)
  const limit = $derived(pageSize === 0 ? Infinity : pageSize + extra)
  const view = $derived.by(() => {
    let left = limit
    let hidden = 0
    const out = sections.map((s) => {
      const open = isOpen(s)
      const take = open ? Math.min(left, s.rows.length) : 0
      left -= take
      if (open) hidden += s.rows.length - take
      return { section: s, open, shown: s.rows.slice(0, take) }
    })
    return { sections: out, hidden }
  })

  function toggleRow(row: T) {
    const key = rowKey(row)
    const next = new Set(expanded)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    expanded = next
  }
  function onExpandKey(event: KeyboardEvent, row: T) {
    if (event.key !== 'Enter') return
    // Enter would also fire a click on a button; handle it once, here.
    event.preventDefault()
    toggleRow(row)
  }

  const detailId = (row: T) => `${uid}-detail-${String(rowKey(row))}`
  const isMuted = (row: T, s: Section) => s.muted || (muted?.(row) ?? false)
  const colCount = $derived(columns.length + (expandable ? 1 : 0))
  const cardColumns = $derived(columns.filter((c) => !c.hideInCards))
  const alignClass = (c: Column<T>) =>
    c.align === 'num' ? 'text-right tabular-nums' : c.align === 'center' ? 'text-center' : 'text-left'

  function display(col: Column<T>, row: T): string {
    const v = col.value ? col.value(row) : (row as Record<string, unknown>)[col.key]
    return v === null || v === undefined ? '' : String(v)
  }
</script>

{#snippet cellContent(col: Column<T>, row: T)}
  {#if col.cell}{@render col.cell(row)}{:else}{display(col, row)}{/if}
{/snippet}

{#snippet expandButton(row: T, extraClass: string)}
  <Button
    variant="ghost"
    size="icon"
    class={cn('size-6', extraClass)}
    aria-label="展开详情"
    aria-expanded={expanded.has(rowKey(row))}
    aria-controls={detailId(row)}
    onclick={() => toggleRow(row)}
    onkeydown={(e: KeyboardEvent) => onExpandKey(e, row)}
  >
    <ChevronRightIcon class={expanded.has(rowKey(row)) ? 'rotate-90' : ''} />
  </Button>
{/snippet}

{#snippet groupLabel(s: Section, open: boolean)}
  {#if s.group?.collapsible}
    <button
      type="button"
      class="inline-flex items-center gap-1 text-xs font-medium"
      aria-expanded={open}
      onclick={() => toggleGroup(s)}
    >
      <ChevronRightIcon class={cn('size-3.5', open && 'rotate-90')} aria-hidden="true" />
      {s.label}（{s.rows.length}）
    </button>
  {:else}
    <span class="text-xs font-medium">{s.label}（{s.rows.length}）</span>
  {/if}
{/snippet}

{#if asCards}
  <div class="grid gap-3">
    {#if caption}<p class="text-xs text-muted-foreground">{caption}</p>{/if}
    {#each view.sections as { section, open, shown } (section.key)}
      <div class="grid gap-2">
        {#if section.label !== undefined}
          <div class={section.muted ? 'text-muted-foreground' : ''}>{@render groupLabel(section, open)}</div>
        {/if}
        {#if open}
          <ul role="list" class="grid gap-2">
            {#each shown as row (rowKey(row))}
              <li
                class={cn(
                  'rounded-md border border-border bg-card p-3 text-sm shadow-1',
                  isMuted(row, section) && 'text-muted-foreground',
                )}
                data-muted={isMuted(row, section) ? 'true' : undefined}
              >
                <dl class="grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1">
                  {#each cardColumns as col (col.key)}
                    <dt class="text-xs text-muted-foreground">{col.cardLabel ?? col.header}</dt>
                    <dd class={cn('min-w-0 break-words', col.align === 'num' && 'tabular-nums')}>
                      {@render cellContent(col, row)}
                    </dd>
                  {/each}
                </dl>
                {#if expandable}
                  <div class="mt-2">
                    {@render expandButton(row, 'w-auto px-2')}
                  </div>
                  {#if expanded.has(rowKey(row))}
                    <div id={detailId(row)} class="mt-2 border-t border-border pt-2">{@render expandable(row)}</div>
                  {/if}
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/each}
  </div>
{:else}
  <Table.Root containerClass="max-lg:overflow-x-auto lg:overflow-visible">
    {#if caption}<Table.Caption class="caption-top">{caption}</Table.Caption>{/if}
    <Table.Header>
      {#if headerGroups}
        <Table.Row class="hover:bg-transparent">
          {#if expandable}<Table.Head class={cn('w-8', sticky && 'sticky top-0 z-10 bg-card')}></Table.Head>{/if}
          {#each headerGroups as g (g.label)}
            <Table.Head
              colspan={g.span}
              class={cn('text-center', sticky && 'sticky top-0 z-10 bg-card')}
            >{g.label}</Table.Head>
          {/each}
        </Table.Row>
      {/if}
      <Table.Row class="hover:bg-transparent">
        {#if expandable}
          <Table.Head class={cn('w-8', sticky && 'z-10 bg-card', sticky && (headerGroups ? 'sticky top-8' : 'sticky top-0'))}>
            <span class="sr-only">展开</span>
          </Table.Head>
        {/if}
        {#each columns as col (col.key)}
          <Table.Head
            title={col.title}
            class={cn(alignClass(col), sticky && 'z-10 bg-card', sticky && (headerGroups ? 'sticky top-8' : 'sticky top-0'))}
          >{col.header}</Table.Head>
        {/each}
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each view.sections as { section, open, shown } (section.key)}
        {#if section.label !== undefined}
          <Table.Row class="bg-muted/50 hover:bg-muted/50">
            <Table.Cell colspan={colCount} class={cn('py-1', section.muted && 'text-muted-foreground')}>
              {@render groupLabel(section, open)}
            </Table.Cell>
          </Table.Row>
        {/if}
        {#if open}
          {#each shown as row (rowKey(row))}
            {@const rowMuted = isMuted(row, section)}
            <Table.Row class={rowMuted ? 'text-muted-foreground' : ''} data-muted={rowMuted ? 'true' : undefined}>
              {#if expandable}
                <Table.Cell class="w-8 py-0 pr-0">{@render expandButton(row, '')}</Table.Cell>
              {/if}
              {#each columns as col (col.key)}
                <Table.Cell class={alignClass(col)}>{@render cellContent(col, row)}</Table.Cell>
              {/each}
            </Table.Row>
            {#if expandable && expanded.has(rowKey(row))}
              <Table.Row class="bg-muted/30 hover:bg-muted/30">
                <Table.Cell colspan={colCount} id={detailId(row)}>{@render expandable(row)}</Table.Cell>
              </Table.Row>
            {/if}
          {/each}
        {/if}
      {/each}
    </Table.Body>
  </Table.Root>
{/if}

{#if view.hidden > 0}
  <div class="pt-2">
    <Button size="sm" onclick={() => (extra += pageSize)}>显示更多（还有 {view.hidden} 行）</Button>
  </div>
{/if}
