<script module lang="ts">
  // At most one box is open per page: opening a term closes the one that was open.
  let closeOpenTerm: (() => void) | null = null
</script>

<script lang="ts">
  import { onDestroy, type Snippet } from 'svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import * as Popover from '$lib/ui/popover/index'
  import { conceptIndex, type ConceptSummary } from '../knowledge'

  // <ConceptTerm id="plan.stop">止损</ConceptTerm>; without content it shows the card's title.
  // The id always comes from `ATTACH` / helpers in knowledge.ts, never from a template literal.
  let { id, children }: { id: string; children?: Snippet } = $props()

  let phase = $state<'loading' | 'ready' | 'failed'>('loading')
  let entry = $state<ConceptSummary | null>(null)
  let failure = $state('')
  let open = $state(false)

  $effect(() => {
    const wanted = id
    let alive = true
    phase = 'loading'
    entry = null
    conceptIndex().then(index => {
      if (!alive) return
      entry = index.get(wanted) ?? null
      phase = 'ready'
    }).catch((e: unknown) => {
      if (!alive) return
      failure = String((e as Error)?.message ?? e)
      phase = 'failed'
    })
    return () => { alive = false }
  })

  const closer = () => { open = false }
  function setOpen(next: boolean) {
    if (!next) {
      open = false
      if (closeOpenTerm === closer) closeOpenTerm = null
      return
    }
    if (closeOpenTerm && closeOpenTerm !== closer) closeOpenTerm()
    closeOpenTerm = closer
    open = true
  }
  onDestroy(() => { if (closeOpenTerm === closer) closeOpenTerm = null })

  // A known card or a failed index gets the button; an id the index does not know is plain text.
  const hasButton = $derived(phase === 'failed' || (phase === 'ready' && entry !== null))
</script>

<svelte:window onkeydown={e => { if (open && e.key === 'Escape') setOpen(false) }} />

<span class="concept-term">
  {#if children}
    <span class={hasButton ? 'border-b border-dotted border-muted-foreground' : ''}>{@render children()}</span>
  {:else if entry}
    <span class="border-b border-dotted border-muted-foreground">{entry.title}</span>
  {:else if phase !== 'loading'}
    <span>{id}</span>
  {/if}{#if hasButton}<Popover.Root bind:open={() => open, setOpen}>
    <Popover.Trigger class="ml-0.5 inline-flex align-middle text-muted-foreground hover:text-primary"
                     aria-label={`概念：${entry?.title ?? id}`}>
      <Icon name="info" />
    </Popover.Trigger>
    <Popover.Content class="w-auto max-w-prose gap-1 p-2 text-xs font-normal" role="note">
      {#if entry}
        <span class="block font-medium">{entry.title}</span>
        <span class="block">{entry.summary}</span>
        <span class="block text-muted-foreground"><code>{entry.ref}</code></span>
        <span class="block"><a class="text-primary underline" href={`#knowledge/${entry.id}`}>看完整卡</a></span>
      {:else}
        <span class="block">概念卡暂不可用：{failure}</span>
      {/if}
    </Popover.Content>
  </Popover.Root>{/if}
</span>
