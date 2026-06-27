type Theme = 'light' | 'dark'

export function getTheme(): Theme {
  return (document.documentElement.getAttribute('data-theme') as Theme) ?? 'light'
}

export function applyTheme(): void {
  const saved = (localStorage.getItem('theme') as Theme) ?? 'light'
  document.documentElement.setAttribute('data-theme', saved)
}

export function toggleTheme(): void {
  const next: Theme = getTheme() === 'dark' ? 'light' : 'dark'
  document.documentElement.setAttribute('data-theme', next)
  localStorage.setItem('theme', next)
}
