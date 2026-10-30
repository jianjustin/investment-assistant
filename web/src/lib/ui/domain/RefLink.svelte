<script lang="ts">
  import ConceptTerm from '$lib/components/ConceptTerm.svelte'
  import { Button } from '$lib/ui/button/index'
  import { conceptId, knowHref, refKind } from '$lib/growth'

  // One reference of a list (what RefList renders per item): fact: calls back with the key (page scrolls to it),
  // call: toggles that tool call (only when the caller can expand it: `onCall` given), know: links to that version,
  // concept: opens the card in place, anything else (user: …) is plain text. The list wrapper and the expanded
  // call region stay with the caller.
  let { ref, onFact, onCall, expanded = false }: {
    ref: string; onFact?: (key: string) => void; onCall?: (ref: string) => void; expanded?: boolean
  } = $props()

  const kind = $derived(refKind(ref))
</script>

{#if kind === 'fact' && onFact}
  <Button variant="link" size="sm" class="select-text text-[length:inherit] font-normal" onclick={() => onFact?.(ref.slice('fact:'.length))}>{ref}</Button>
{:else if kind === 'call' && onCall}
  <Button variant="link" size="sm" class="select-text text-[length:inherit] font-normal" aria-expanded={expanded} onclick={() => onCall?.(ref)}>{ref}</Button>
{:else if kind === 'know'}
  <a class="text-primary underline" href={knowHref(ref)}>{ref}</a>
{:else if kind === 'concept'}
  <ConceptTerm id={conceptId(ref)}>{ref}</ConceptTerm>
{:else}
  <span>{ref}</span>
{/if}
