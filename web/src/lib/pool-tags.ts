/** Watchlist tags <-> pool tier conversion; the backend enforces the same rules on write. */

export const SECTOR_ETFS = ['SMH', 'XLK', 'QQQ'] as const

export function isCore(tags: string[]): boolean {
  return (tags ?? []).some(t => t.trim().toLowerCase() === 'core')
}

export function sectorOf(tags: string[]): string | null {
  const tagged = (tags ?? []).find(t => t.trim().toLowerCase().startsWith('sector:'))
  if (!tagged) return null
  const etf = tagged.slice('sector:'.length).trim().toUpperCase()
  return (SECTOR_ETFS as readonly string[]).includes(etf) ? etf : null
}

export function withPoolTags(tags: string[], core: boolean, sector: string | null): string[] {
  const others = (tags ?? []).filter(t => {
    const lower = t.trim().toLowerCase()
    return lower !== 'core' && !lower.startsWith('sector:')
  })
  const out = [...others]
  if (core) out.push('core')
  if (sector) out.push(`sector:${sector}`)
  return out
}
