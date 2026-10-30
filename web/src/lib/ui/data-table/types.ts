import type { Snippet } from 'svelte'

export type ColumnAlign = 'left' | 'num' | 'center'

export type Column<T> = {
  key: string
  header: string
  /** `num` = right-aligned with tabular numerals. */
  align?: ColumnAlign
  /** Tooltip on the header (abbreviation explanations). */
  title?: string
  /** Custom cell; without it the value is rendered as text. */
  cell?: Snippet<[T]>
  /** Plain-text accessor; defaults to `row[key]`. */
  value?: (row: T) => string | number | null
  /** Field name in card mode; defaults to `header`. */
  cardLabel?: string
  hideInCards?: boolean
}

export type RowGroup<T> = {
  key: string
  label: string
  rows: T[]
  /** Greyed-out group (ended, voided, superseded rows). */
  muted?: boolean
  collapsible?: boolean
  /** Initial state of a collapsible group; the user's clicks take over afterwards. */
  open?: boolean
  onToggle?: (open: boolean) => void
}

export type HeaderGroup = { label: string; span: number }
