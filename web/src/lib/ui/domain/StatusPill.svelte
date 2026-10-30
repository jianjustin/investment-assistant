<script lang="ts">
  import { Badge } from '$lib/ui/badge/index'
  import { cn } from '$lib/utils.js'
  import { statusOf, type StatusDomain, type Tone } from './status'

  // The only way to show a status. Colour carries the tone, the label is always text. `text` replaces the label
  // (for templates with placeholders, e.g. EXECUTION_TEXT.adopted once filled in); the tone still comes from the table.
  let { domain, value, text, title }: { domain: StatusDomain; value: string; text?: string; title?: string } = $props()

  // The label stays in text-foreground: tinted text on a tinted pill is under 4.5:1 in the light theme
  // (success / warn / destructive ~3.7-4.0), so the tone is carried by the dot, the border and the tint.
  const PILL: Record<Tone, { box: string; dot: string }> = {
    success: { box: 'border-success/40 bg-success/10', dot: 'bg-success' },
    warn: { box: 'border-warn/40 bg-warn/10', dot: 'bg-warn' },
    danger: { box: 'border-destructive/40 bg-destructive/10', dot: 'bg-destructive' },
    info: { box: 'border-info/40 bg-info/10', dot: 'bg-info' },
    running: { box: 'border-running/40 bg-running/10', dot: 'bg-running' },
    neutral: { box: 'border-neutral/40 bg-neutral/10', dot: 'bg-neutral' },
  }

  const info = $derived(statusOf(domain, value))
  const look = $derived(PILL[info.tone])
</script>

<Badge
  {title}
  data-domain={domain}
  data-status={value}
  data-tone={info.tone}
  class={cn('text-foreground', look.box, info.tone === 'running' && 'animate-running')}
>
  <span class={cn('size-1.5 shrink-0 rounded-full', look.dot)} aria-hidden="true"></span>
  {text ?? info.label}
</Badge>
