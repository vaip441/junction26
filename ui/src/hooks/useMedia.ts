import { useCallback, useSyncExternalStore } from 'react'

/** Whether a media query matches, kept current as the window changes. */
export function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (changed: () => void) => {
      const media = window.matchMedia(query)
      media.addEventListener('change', changed)
      return () => media.removeEventListener('change', changed)
    },
    [query],
  )
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
}
