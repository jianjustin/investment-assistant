<script lang="ts">
  import * as Dialog from '$lib/ui/dialog/index.js'
  import { Button } from '$lib/ui/button/index.js'

  let {
    open = $bindable(false),
    title,
    consequence,
    actionLabel,
    destructive = false,
    busy = false,
    onConfirm,
    onCancel,
  }: {
    open: boolean
    title: string
    /** One sentence: what happens when the user confirms. */
    consequence: string
    /** The action's name, never a generic "确定". */
    actionLabel: string
    destructive?: boolean
    busy?: boolean
    onConfirm: () => void | Promise<void>
    onCancel?: () => void
  } = $props()

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

  function restoreFocus(event: Event) {
    event.preventDefault()
    opener?.focus()
    opener = null
  }
</script>

<Dialog.Root {open} {onOpenChange}>
  <Dialog.Content showCloseButton={false} onCloseAutoFocus={restoreFocus}>
    <Dialog.Header>
      <Dialog.Title>{title}</Dialog.Title>
      <Dialog.Description>{consequence}</Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button variant="outline" disabled={busy} onclick={() => onOpenChange(false)}>取消</Button>
      <Button
        variant={destructive ? 'destructive' : 'primary'}
        {busy}
        onclick={() => onConfirm()}
      >{actionLabel}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
