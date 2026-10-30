<script lang="ts">
  // `口径 review-8`: the calculation version in code style, linked to its concept card when `concept` is given.
  let { version, concept }: { version: string; concept?: string } = $props()
</script>

<span class="text-xs text-muted-foreground">口径
  {#if concept}<a href={`#knowledge/${concept}`} class="text-primary underline underline-offset-2"><code class="rounded-sm bg-muted px-0.5 font-mono">{version}</code></a>{:else}<code class="rounded-sm bg-muted px-0.5 font-mono">{version}</code>{/if}</span>
