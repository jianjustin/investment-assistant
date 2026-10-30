<script lang="ts">
  import type { Snippet } from 'svelte'
  import * as Dialog from '$lib/ui/dialog/index.js'
  import { Button } from '$lib/ui/button/index.js'

  let {
    open = $bindable(false),
    title,
    consequence,
    actionLabel,
    destructive = false,
    busy = false,
    confirmDisabled = false,
    onConfirm,
    onCancel,
    children,
  }: {
    open: boolean
    title: string
    /** One sentence: what happens when the user confirms. */
    consequence: string
    /** The action's name, never a generic "确定". */
    actionLabel: string
    destructive?: boolean
    busy?: boolean
    /** Disables the action button only (e.g. a required field in `children` is still empty). */
    confirmDisabled?: boolean
    onConfirm: () => void | Promise<void>
    onCancel?: () => void
    /** Optional form body, rendered between the description and the buttons. */
    children?: Snippet
  } = $props()

  let cancelButton = $state<HTMLElement | null>(null)

  // Remember who had focus when the dialog opened and give it back on close.
  let opener: HTMLElement | null = null
  let wasOpen = false
  $effect.pre(() => {
    if (open && !wasOpen) {
      const active = document.activeElement
      opener = active instanceof HTMLElement && active !== document.body ? active : null
    }
    wasOpen = open
  })

  function onOpenChange(next: boolean) {
    if (next) return
    // While the request is in flight the dialog stays put.
    if (busy) return
    open = false
    onCancel?.()
  }

  // The safe choice is focused first, whatever the body contains.
  function focusCancel(event: Event) {
    if (busy) return                // both buttons are disabled: let Bits focus the dialog itself
    event.preventDefault()
    cancelButton?.focus()
  }

  function restoreFocus(event: Event) {
    event.preventDefault()
    opener?.focus()
    opener = null
  }
</script>

<!-- Function binding: Bits writes through onOpenChange only, so its inner state can never diverge from `open`. -->
<Dialog.Root bind:open={() => open, (value) => onOpenChange(value)}>
  <Dialog.Content
    showCloseButton={false}
    onOpenAutoFocus={focusCancel}
    onCloseAutoFocus={restoreFocus}
    escapeKeydownBehavior={busy ? 'ignore' : 'close'}
    interactOutsideBehavior={busy ? 'ignore' : 'close'}
  >
    <Dialog.Header>
      <Dialog.Title>{title}</Dialog.Title>
      <Dialog.Description>{consequence}</Dialog.Description>
    </Dialog.Header>
    {@render children?.()}
    <Dialog.Footer>
      <Button bind:ref={cancelButton} variant="outline" disabled={busy} onclick={() => onOpenChange(false)}>取消</Button>
      <Button
        variant={destructive ? 'destructive' : 'primary'}
        {busy}
        disabled={confirmDisabled}
        onclick={() => onConfirm()}
      >{actionLabel}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
