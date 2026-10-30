import { createSubscriber } from 'svelte/reactivity'

/** Below Tailwind's `md` breakpoint (768px). */
export const NARROW_QUERY = '(max-width: 767px)'

/**
 * Reactive "is the viewport narrow" flag. Without `matchMedia` (jsdom, old browsers) or when it throws,
 * the answer is always `false`, i.e. the desktop layout.
 */
export function useNarrow(): { readonly current: boolean } {
  let query: MediaQueryList | undefined
  try {
    query = window.matchMedia?.(NARROW_QUERY)
  } catch {
    query = undefined
  }
  const mql = query
  if (!mql) return { get current() { return false } }

  const subscribe = createSubscriber((update) => {
    if (mql.addEventListener) {
      mql.addEventListener('change', update)
      return () => mql.removeEventListener('change', update)
    }
    // very old WebKit only has the deprecated pair
    mql.addListener?.(update)
    return () => mql.removeListener?.(update)
  })

  return {
    get current() {
      subscribe()
      return Boolean(mql.matches)
    },
  }
}
