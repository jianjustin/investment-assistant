/** Shared guard for active editors. Hash listeners share one atomic decision per event. */
type DraftGuard = {
  snapshot: () => string
  dirty: () => boolean
  discard: (snapshot: string) => void
}
const guards = new Set<DraftGuard | (() => boolean)>()
const decisions = new WeakMap<Event, boolean>()

export function registerNavigationGuard(guard: DraftGuard | (() => boolean)): () => void {
  guards.add(guard)
  return () => { guards.delete(guard) }
}

/** A cutoff response must not unmount drafts typed after that read began. */
export function captureResearchDrafts(): () => boolean {
  const snapshots = [...guards].filter((guard): guard is DraftGuard => typeof guard !== 'function')
    .map(guard => ({ guard, snapshot: guard.snapshot() }))
  return () => snapshots.every(({ guard, snapshot }) => guards.has(guard) && guard.snapshot() === snapshot)
}

export function confirmResearchNavigation(): boolean {
  const drafts: { guard: DraftGuard; snapshot: string }[] = []
  for (const guard of guards) {
    if (typeof guard === 'function') { if (!guard()) return false }
    else if (guard.dirty()) drafts.push({ guard, snapshot: guard.snapshot() })
  }
  if (drafts.length && !window.confirm('研究编辑有未保存内容，离开或刷新将放弃这些编辑。继续？')) return false
  // No editor is discardable until the entire transition has been accepted.
  for (const { guard, snapshot } of drafts) guard.discard(snapshot)
  return true
}

export function guardHashNavigation(event: HashChangeEvent, previousHash: string): boolean {
  const decided = decisions.get(event)
  if (decided !== undefined) return decided
  const allowed = confirmResearchNavigation()
  decisions.set(event, allowed)
  if (!allowed) {
    const prior = event.oldURL ? new URL(event.oldURL).hash : previousHash
    history.replaceState(null, '', prior)
  }
  return allowed
}
