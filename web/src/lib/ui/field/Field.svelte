<script lang="ts">
  import type { Snippet } from 'svelte'
  import { Label } from '$lib/ui/label/index.js'

  let {
    label,
    id,
    hint,
    error = null,
    required = false,
    children,
  }: {
    label: string
    id: string
    hint?: string
    error?: string | null
    required?: boolean
    children: Snippet<[{ id: string; describedby: string | undefined; invalid: boolean }]>
  } = $props()

  const hintId = $derived(`${id}-hint`)
  const errorId = $derived(`${id}-error`)
  const describedby = $derived([hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined)
</script>

<div class="grid gap-1.5" data-slot="field">
  <div class="flex items-center gap-1">
    <Label for={id}>{label}</Label>
    {#if required}<span aria-hidden="true" class="text-sm leading-none text-destructive">*</span>{/if}
  </div>
  {@render children({ id, describedby, invalid: Boolean(error) })}
  {#if hint}<p id={hintId} class="text-xs text-muted-foreground">{hint}</p>{/if}
  {#if error}<p id={errorId} role="alert" class="text-xs text-destructive">{error}</p>{/if}
</div>
