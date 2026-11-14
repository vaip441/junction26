/**
 * The site behind a tick's `source` ("x.com/handle", "reddit.com/r/sub", "truthsocial.com/@realDonaldTrump",
 * "reuters.com"), for its logo.
 * Spoken and typed ticks have no site.
 */
export function sourceDomain(source: string): string | null {
  const host = source.replace(/^https?:\/\//, '').split('/')[0].replace(/^www\./, '')
  return host.includes('.') ? host : null
}

/** A small logo for a site, from Google's favicon service. */
export function faviconUrl(domain: string, size = 32): string {
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=${size}`
}

export function shortSource(source: string): string {
  return source.replace(/^reddit\.com\/r\//, 'r/').replace(/^truthsocial\.com\/@/, '@').replace(/^www\./, '')
}
