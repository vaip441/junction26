"""The image a page offers as its own, read from its metadata when the tape is hovered, and remembered.

The news search names a page and its passages, not its picture. A page declares one with Open Graph,
Twitter cards or `link rel=image_src`; reading it costs no Context.dev credit, so the preview is looked up
once per address and kept. Nothing private is read: a page's host must resolve to a public address.
"""
import asyncio
import html
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from terminal import http, posts
from terminal import db as store

log = logging.getLogger(__name__)

MAX_BYTES = 200_000  # metadata lives at the top of a page: stop reading once it cannot be further down
MAX_REDIRECTS = 4
TIMEOUT = 8
CACHED_SECONDS = 7 * 86400  # a found image stays for a week
RETRY_SECONDS = 3600  # a page that gave none is tried again after an hour
IMAGE_KEYS = ("og:image:secure_url", "og:image:url", "og:image", "twitter:image", "twitter:image:src", "image")
TITLE_KEYS = ("og:title", "twitter:title")

META = re.compile(r"<meta\b[^>]*>", re.I | re.S)
LINK = re.compile(r"<link\b[^>]*>", re.I | re.S)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>/]+))""", re.S)

_http = http.client(TIMEOUT, follow_redirects=False, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))


class PreviewError(Exception):
    pass


def _attrs(tag: str) -> dict[str, str]:
    return {name.lower(): html.unescape(next((v for v in values if v), ""))
            for name, *values in ATTR.findall(tag)}


def _absolute(url: str, base: str) -> str | None:
    """A declared address as an absolute http(s) one, or None when it cannot be shown."""
    full = urljoin(base, url.strip())
    parts = urlsplit(full)
    return full if parts.scheme in ("http", "https") and parts.netloc else None


def image_from_html(text: str, base: str) -> tuple[str | None, str | None]:
    """(preview image, page title) a page declares, the image absolute. Either may be None."""
    found: dict[str, str] = {}
    for tag in META.findall(text):
        attributes = _attrs(tag)
        name = (attributes.get("property") or attributes.get("name") or "").strip().lower()
        if name and attributes.get("content") and name not in found:
            found[name] = attributes["content"]
    if "image" not in found:  # the older spelling, on a link rather than a meta
        for tag in LINK.findall(text):
            attributes = _attrs(tag)
            if "image_src" in (attributes.get("rel") or "").lower().split() and attributes.get("href"):
                found["image"] = attributes["href"]
                break
    image = next((seen for seen in (_absolute(found[k], base) for k in IMAGE_KEYS if found.get(k)) if seen), None)
    title = next((found[k].strip() for k in TITLE_KEYS if found.get(k, "").strip()), None)
    if title is None and (match := TITLE.search(text)):
        title = html.unescape(" ".join(match.group(1).split())) or None
    return image, title


async def _check_public(url: str) -> None:
    """Refuse an address whose host is not public: this endpoint takes any URL a page named, not local ones."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PreviewError("not an http(s) address")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise PreviewError(f"cannot resolve {parts.hostname}: {e}") from e
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError as e:
            raise PreviewError(f"odd address for {parts.hostname}") from e
        if not address.is_global:
            raise PreviewError(f"{parts.hostname} is not a public address")


async def read_page(url: str) -> tuple[str, str]:
    """(the first part of a page's HTML, the address it finally came from). Redirects are followed only to
    public addresses, and the read stops once the metadata cannot be further down."""
    for _ in range(MAX_REDIRECTS + 1):
        await _check_public(url)
        async with _http().stream("GET", url, headers={"User-Agent": posts.UA,
                                                       "Accept": "text/html,application/xhtml+xml"}) as r:
            if r.has_redirect_location:
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            if content_type and "html" not in content_type:
                raise PreviewError(f"not an HTML page: {content_type}")
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break
            return body.decode(r.encoding or "utf-8", "replace"), str(r.url)
    raise PreviewError("too many redirects")


async def preview(db, url: str, *, now: float | None = None, read=None) -> dict:
    """{"url", "image", "title"} for a page, from the store when it is fresh. A page without an image is
    retried after an hour, so a fleeting failure does not leave the tape without one for long."""
    now = time.time() if now is None else now
    seen = store.get_preview(db, url)
    if seen is not None and now - seen["fetched_ts"] < (CACHED_SECONDS if seen["image"] else RETRY_SECONDS):
        return {"url": url, "image": seen["image"], "title": seen["title"]}
    image = title = None
    try:
        text, final = await (read or read_page)(url)
        image, title = image_from_html(text, final)
    except Exception as e:  # a page that cannot be read is a page without a preview, not a failed request
        log.info("no preview for %s: %s: %s", url, type(e).__name__, str(e)[:150])
    store.set_preview(db, url, image, title, now)
    return {"url": url, "image": image, "title": title}
