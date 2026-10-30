export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readSaved(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

function save(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // private mode or blocked storage: the switch still works for this page view
  }
}

function systemMedia(): MediaQueryList | null {
  try {
    return window.matchMedia?.(DARK_QUERY) ?? null
  } catch {
    return null
  }
}

function setAttribute(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}

let stopFollowing: (() => void) | null = null

function followSystem(): void {
  stopFollowing?.()
  stopFollowing = null
  const media = systemMedia()
  if (!media?.addEventListener) return
  const onChange = (event: { matches: boolean }) => setAttribute(event.matches ? 'dark' : 'light')
  media.addEventListener('change', onChange)
  stopFollowing = () => media.removeEventListener('change', onChange)
}

export function getTheme(): Theme {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

/** Saved choice wins; otherwise follow the system until the user toggles. */
export function applyTheme(): void {
  const saved = readSaved()
  if (saved) {
    stopFollowing?.()
    stopFollowing = null
    setAttribute(saved)
    return
  }
  setAttribute(systemMedia()?.matches ? 'dark' : 'light')
  followSystem()
}

export function toggleTheme(): void {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark'
  stopFollowing?.()
  stopFollowing = null
  setAttribute(next)
  save(next)
}

/** Fires whenever `data-theme` on <html> changes (toggle, system change, tests). */
export function onThemeChange(callback: (theme: Theme) => void): () => void {
  const observer = new MutationObserver(() => callback(getTheme()))
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => observer.disconnect()
}
