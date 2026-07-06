<script lang="ts">
  import { onMount } from 'svelte'
  import { applyTheme } from './lib/theme'
  import AppShell from './lib/components/AppShell.svelte'
  import Tools from './routes/Tools.svelte'
  import Data from './routes/Data.svelte'
  import Strategy from './routes/Strategy.svelte'
  import Trade from './routes/Trade.svelte'
  import Settings from './routes/Settings.svelte'
  import { parseHash, type Zone } from './lib/router'

  let { zone, sub } = $state(parseHash(location.hash))

  onMount(() => {
    applyTheme()
    const onhashchange = () => {
      const parsed = parseHash(location.hash)
      zone = parsed.zone
      sub = parsed.sub
    }
    window.addEventListener('hashchange', onhashchange)
    return () => window.removeEventListener('hashchange', onhashchange)
  })
</script>

<AppShell route={zone} {sub}>
  {#if zone === 'tools'}
    <Tools {sub} />
  {:else if zone === 'data'}
    <Data {sub} />
  {:else if zone === 'strategy'}
    <Strategy {sub} />
  {:else if zone === 'trade'}
    <Trade {sub} />
  {:else}
    <Settings {sub} />
  {/if}
</AppShell>
