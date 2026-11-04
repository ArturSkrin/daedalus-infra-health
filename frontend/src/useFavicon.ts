import { useEffect } from 'react'
import { LEVEL } from './theme'
import type { Level } from './types'

// The same mark as public/favicon.svg, in one colour.
function icon(color: string): string {
  const ring = `<circle cx="16" cy="16" r="10" fill="none" stroke="${color}" stroke-width="4.5"`
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="7" fill="#0a0a0f"/>' +
    `${ring} stroke-opacity=".22"/>` +
    `${ring} stroke-linecap="round" stroke-dasharray="50.3 62.83" transform="rotate(-90 16 16)"/></svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

// The tab wears the verdict's colour, so the decision is visible while the tracker sits in a background tab.
// No verdict (still loading, or a live source that stopped answering) is grey: "we do not know", never "fine".
export function useFavicon(level: Level | undefined) {
  useEffect(() => {
    const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
    if (link) link.href = icon(LEVEL[level ?? 'muted'].color)
  }, [level])
}
