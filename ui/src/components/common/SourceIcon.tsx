import { useState } from 'react'
import { faviconUrl, sourceDomain } from '../../lib/sources'

/** The site's logo, or nothing for sources without a site (the mic, the keyboard) or when it fails to load. */
export function SourceIcon({ source, className = 'h-3.5 w-3.5' }: { source: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  const domain = sourceDomain(source)
  if (!domain || failed) return null
  return (
    <img
      src={faviconUrl(domain)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-sm bg-white/90 p-px ${className}`}
    />
  )
}
