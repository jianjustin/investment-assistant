<script lang="ts">
  import { onMount } from 'svelte'
  import { applyTheme } from './lib/theme'
  import AppShell from './lib/components/AppShell.svelte'
  import Tools from './routes/Tools.svelte'
  import Settings from './routes/Settings.svelte'
  import Today from './routes/Today.svelte'
  import Instrument from './routes/Instrument.svelte'
  import Review from './routes/Review.svelte'
  import Data from './routes/Data.svelte'
  import { guardHashNavigation } from './lib/navigation-guard'
  import { parseHash, type Zone } from './lib/router'

  let { zone, sub } = $state(parseHash(location.hash))

  onMount(() => {
    applyTheme()
    let previousHash = location.hash
    const onhashchange = (event: HashChangeEvent) => {
      if (!guardHashNavigation(event, previousHash)) return
      previousHash = location.hash
      const parsed = parseHash(location.hash)
      zone = parsed.zone
      sub = parsed.sub
    }
    window.addEventListener('hashchange', onhashchange)
    return () => window.removeEventListener('hashchange', onhashchange)
  })
</script>

<AppShell route={zone} {sub}>
  {#if zone === 'today'}
    <Today />
  {:else if zone === 'instrument'}
    <Instrument {sub} />
  {:else if zone === 'review'}
    <Review {sub} />
  {:else if zone === 'data'}
    <Data {sub} />
  {:else if zone === 'tools'}
    <Tools {sub} />
  {:else if zone === 'settings'}
    <Settings {sub} />
  {/if}
</AppShell>
