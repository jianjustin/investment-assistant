export type Zone = 'tools' | 'data' | 'strategy' | 'trade' | 'settings' | 'technicals'
export const zones: Zone[] = ['tools', 'data', 'strategy', 'trade', 'settings', 'technicals']

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, rawSub] = hash.replace(/^#/, '').split('/')
  const zone = zones.includes(rawZone as Zone) ? (rawZone as Zone) : 'tools'
  return { zone, sub: rawSub || undefined }
}
