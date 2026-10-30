<script lang="ts">
  import { codeSegments } from '../data-families'

  // Inline text whose `backtick` runs render as code instead of raw backticks.
  let { text }: { text: string } = $props()
</script>

{#each codeSegments(text) as part}{#if part.code}<code class="px-0.5 rounded-sm bg-muted font-mono">{part.text}</code>{:else}{part.text}{/if}{/each}
