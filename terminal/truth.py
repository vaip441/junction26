"""Trump's Truth Social posts as ticks, read from the feed file the team's scraper appends to
(trump-social-scraper/, `watch --jsonl`). The scraper runs on its own; only its file is read here."""
import json
import logging
import time
from datetime import datetime

from terminal import db as store
from terminal import posts
from terminal.pipeline import clean, ingest
from terminal.poller import forever

log = logging.getLogger(__name__)
SOURCE = "truthsocial.com/@realDonaldTrump"
WINDOW = 86400  # a post counts for a day, like the searches' "last 24 hours"


def item(post: dict) -> dict | None:
    """What to score from one line of the feed; None for a post that is only a picture or a video."""
    parts = [p for p in (post.get("text"), post.get("quote_text"), post.get("link_title")) if p]
    if not parts:
        return None
    who = f"Retruth of @{post['retruth_of']}: " if post.get("retruth_of") else ""
    return {"url": post["url"], "headline": who + clean(parts[0], 250), "body": "\n".join(parts),
            "published": datetime.fromisoformat(post["created_at"]).timestamp()}


def read_new(path: str, offset: int) -> tuple[list[dict], int]:
    """The posts appended to the feed file since `offset`, and where to read from next time."""
    try:
        with open(path, "rb") as f:
            if f.seek(0, 2) < offset:
                offset = 0  # the file was replaced by a shorter one
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return [], offset
    whole = data[:data.rfind(b"\n") + 1]  # a line still being written waits for its end
    found = []
    for line in whole.splitlines():
        try:
            if isinstance(post := json.loads(line), dict):
                found.append(post)
        except ValueError:
            log.warning("unreadable line in %s: %r", path, line[:80])
    return found, offset + len(whole)


async def ingest_post(db, bus, scorer, post: dict, now: float | None = None) -> int:
    """Score a post for every polled market whose queries it shares a word with. Returns the ticks stored."""
    now = time.time() if now is None else now
    it = item(post)
    if it is None or it["published"] < now - WINDOW:
        return 0
    stored = 0
    for m in store.list_markets(db):
        if m["poll_seconds"] > 0 and posts.shares_words(it["body"], m["queries"]):
            # a post made while the scraper was down arrives late: it is history, not a live tick
            tick = await ingest(db, bus, scorer, m, kind="post", source=SOURCE, headline=it["headline"], url=it["url"],
                                body=it["body"], published_ts=it["published"], backfill=not post.get("live", True), now=now)
            stored += tick is not None
    return stored


async def truth_loop(db, bus, scorer, path: str, interval: float = 2) -> None:
    """Follow the feed file. It is read from its start after a restart; what is already stored is skipped.

    shortcut: a post whose scoring fails is not retried until the next restart re-reads the file;
    keep the offset back when that starts to matter.
    """
    offset = 0

    async def step() -> None:
        nonlocal offset
        found, offset = read_new(path, offset)
        for post in found:
            await ingest_post(db, bus, scorer, post)

    await forever("truth feed", interval, step)
