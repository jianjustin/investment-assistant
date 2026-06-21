export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

export function compactLines(output: string | undefined, fallback: string): string {
  const lines = (output ?? '').split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.slice(0, 8).join('\n') || fallback
}
