import { useEffect, useState } from 'react'

const QUERY = '(max-width: 639px)'

// Phone-sized viewport. Ring sizes are numeric SVG props, so CSS breakpoints
// alone cannot shrink them.
export function useCompact(): boolean {
  const [compact, setCompact] = useState(() => window.matchMedia(QUERY).matches)
  useEffect(() => {
    const media = window.matchMedia(QUERY)
    const onChange = () => setCompact(media.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])
  return compact
}
