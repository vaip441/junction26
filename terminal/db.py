"""SQLite store: markets (related contracts are rows pointing at their lead market), ticks, prices.

Prices are percentages 0..100 and timestamps are unix seconds, everywhere.
"""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY, venue TEXT NOT NULL, venue_ref TEXT, title TEXT NOT NULL, rules TEXT NOT NULL,
    url TEXT, lead_id TEXT, queries TEXT NOT NULL DEFAULT '[]', poll_seconds INTEGER NOT NULL DEFAULT 900,
    filled INTEGER NOT NULL DEFAULT 0, companies TEXT,
    created_ts REAL NOT NULL DEFAULT (unixepoch('subsec')));
CREATE TABLE IF NOT EXISTS prices (
    market_id TEXT NOT NULL, ts REAL NOT NULL, price REAL NOT NULL, PRIMARY KEY (market_id, ts));
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY, market_id TEXT NOT NULL, ts REAL NOT NULL, published_ts REAL, kind TEXT NOT NULL,
    source TEXT NOT NULL, url TEXT, headline TEXT NOT NULL, up REAL NOT NULL, none REAL NOT NULL, down REAL NOT NULL,
    strength REAL NOT NULL, verdict TEXT NOT NULL, confidence REAL NOT NULL, price_at REAL,
    test INTEGER NOT NULL, backfill INTEGER NOT NULL, hidden INTEGER NOT NULL, dedupe_key TEXT NOT NULL,
    date_checked INTEGER NOT NULL DEFAULT 0, likes INTEGER, replies INTEGER, title_key TEXT, rule TEXT,
    UNIQUE (market_id, dedupe_key));
CREATE INDEX IF NOT EXISTS ticks_by_market ON ticks (market_id, ts);
CREATE INDEX IF NOT EXISTS ticks_by_url ON ticks (url);
"""
TICK_COLS = ("market_id", "ts", "published_ts", "kind", "source", "url", "headline", "up", "none", "down", "strength",
             "verdict", "confidence", "price_at", "test", "backfill", "hidden", "dedupe_key")
# likes and replies: posts on X; title_key: articles; rule: the rules sentence behind a tick that moves the price
OPTIONAL_COLS = ("likes", "replies", "title_key", "rule")


def connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # autocommit: every write is durable
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    if "filled" not in {r["name"] for r in db.execute("PRAGMA table_info(markets)")}:  # stores created before 13 Nov
        db.execute("ALTER TABLE markets ADD COLUMN filled INTEGER NOT NULL DEFAULT 0")
    if "companies" not in {r["name"] for r in db.execute("PRAGMA table_info(markets)")}:  # stores from before 14 Nov noon
        db.execute("ALTER TABLE markets ADD COLUMN companies TEXT")
    if "title_key" not in {r["name"] for r in db.execute("PRAGMA table_info(ticks)")}:  # stores from before 14 Nov noon
        db.execute("ALTER TABLE ticks ADD COLUMN title_key TEXT")
        db.execute("ALTER TABLE ticks ADD COLUMN rule TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS ticks_by_title ON ticks (market_id, title_key)")
    if "date_checked" not in {r["name"] for r in db.execute("PRAGMA table_info(ticks)")}:  # stores from before 14 Nov
        db.execute("ALTER TABLE ticks ADD COLUMN date_checked INTEGER NOT NULL DEFAULT 0")
    if "likes" not in {r["name"] for r in db.execute("PRAGMA table_info(ticks)")}:  # stores from before 14 Nov evening
        db.execute("ALTER TABLE ticks ADD COLUMN likes INTEGER")
        db.execute("ALTER TABLE ticks ADD COLUMN replies INTEGER")
    return db


def _market(row) -> dict | None:
    return row and {**row, "queries": json.loads(row["queries"]), "filled": bool(row["filled"]),
                    "companies": row["companies"] and json.loads(row["companies"])}  # None: not asked for yet


def _tick(row) -> dict:
    return {**row, "test": bool(row["test"]), "backfill": bool(row["backfill"]), "hidden": bool(row["hidden"]),
            "rule": row["rule"] and json.loads(row["rule"])}


def add_market(db, *, id, venue, venue_ref, title, rules, url, lead_id=None, queries=(), poll_seconds=900) -> dict:
    db.execute("INSERT OR IGNORE INTO markets (id, venue, venue_ref, title, rules, url, lead_id, queries, poll_seconds)"
               " VALUES (?,?,?,?,?,?,?,?,?)",
               (id, venue, venue_ref, title, rules, url, lead_id, json.dumps(list(queries)), poll_seconds))
    return get_market(db, id)


def set_queries(db, id: str, queries: list[str]) -> None:
    db.execute("UPDATE markets SET queries = ? WHERE id = ?", (json.dumps(queries), id))


def set_companies(db, id: str, companies: list[str]) -> None:
    """The companies a market is about, whose news is followed; an empty list when it is about none."""
    db.execute("UPDATE markets SET companies = ? WHERE id = ?", (json.dumps(companies), id))


def set_filled(db, id: str) -> None:
    """The market's first article pass (its backfill) has completed; later passes are live."""
    db.execute("UPDATE markets SET filled = 1 WHERE id = ?", (id,))


def set_poll_seconds(db, id: str, seconds: int) -> None:
    """0 means the market is never polled for articles."""
    db.execute("UPDATE markets SET poll_seconds = ? WHERE id = ?", (seconds, id))


def promote(db, id: str) -> None:
    """Turn a related contract into a market of its own."""
    db.execute("UPDATE markets SET lead_id = NULL WHERE id = ?", (id,))


def delete_market(db, id: str) -> None:
    """Remove a market, its related contracts, and all their ticks and prices."""
    for (mid,) in db.execute("SELECT id FROM markets WHERE id = ? OR lead_id = ?", (id, id)).fetchall():
        db.execute("DELETE FROM ticks WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM prices WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM markets WHERE id = ?", (mid,))


def get_market(db, id: str) -> dict | None:
    return _market(db.execute("SELECT * FROM markets WHERE id = ?", (id,)).fetchone())


def list_markets(db) -> list[dict]:
    return [_market(r) for r in db.execute("SELECT * FROM markets WHERE lead_id IS NULL ORDER BY created_ts, id")]


def related(db, lead_id: str) -> list[dict]:
    return [_market(r) for r in db.execute("SELECT * FROM markets WHERE lead_id = ? ORDER BY rowid", (lead_id,))]  # as added


def all_priced(db) -> list[dict]:
    return [_market(r) for r in db.execute("SELECT * FROM markets WHERE venue != 'made_up'")]


def add_price(db, market_id: str, ts: float, price: float) -> None:
    db.execute("INSERT OR REPLACE INTO prices (market_id, ts, price) VALUES (?,?,?)", (market_id, ts, price))


def price_at(db, market_id: str, ts: float) -> float | None:
    row = db.execute("SELECT price FROM prices WHERE market_id = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                     (market_id, ts)).fetchone()
    return row and row["price"]


def latest_price(db, market_id: str) -> tuple[float, float] | None:
    """(ts, price) of the newest sample."""
    row = db.execute("SELECT ts, price FROM prices WHERE market_id = ? ORDER BY ts DESC LIMIT 1", (market_id,)).fetchone()
    return row and (row["ts"], row["price"])


def prices(db, market_id: str, since: float = 0) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT ts, price FROM prices WHERE market_id = ? AND ts >= ? ORDER BY ts",
                                        (market_id, since))]


def has_tick(db, market_id: str, dedupe_key: str) -> bool:
    return db.execute("SELECT 1 FROM ticks WHERE market_id = ? AND dedupe_key = ?",
                      (market_id, dedupe_key)).fetchone() is not None


def has_title(db, market_id: str, title_key: str) -> bool:
    """Whether this market already has an article with this headline, from any outlet or address."""
    return db.execute("SELECT 1 FROM ticks WHERE market_id = ? AND title_key = ?", (market_id, title_key)).fetchone() is not None


def add_tick(db, tick: dict) -> dict | None:
    """Store a tick; None if this market already has one with the same dedupe_key."""
    cols = TICK_COLS + OPTIONAL_COLS
    cur = db.execute(f"INSERT OR IGNORE INTO ticks ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [tick[c] for c in TICK_COLS] + [tick.get(c) for c in OPTIONAL_COLS])
    if not cur.rowcount:
        return None
    return _tick(db.execute("SELECT * FROM ticks WHERE id = ?", (cur.lastrowid,)).fetchone())


def ticks(db, market_id: str, limit: int = 100, include_hidden: bool = False) -> list[dict]:
    hidden = "" if include_hidden else "AND hidden = 0"
    return [_tick(r) for r in db.execute(
        f"SELECT * FROM ticks WHERE market_id = ? {hidden} ORDER BY ts DESC, id DESC LIMIT ?", (market_id, limit))]


def recent_headlines(db, market_id: str, limit: int = 12) -> list[str]:
    """Headlines of the latest shown, real (not spoken or typed) ticks, newest first."""
    return [r["headline"] for r in db.execute(
        "SELECT headline FROM ticks WHERE market_id = ? AND hidden = 0 AND test = 0 ORDER BY ts DESC, id DESC LIMIT ?",
        (market_id, limit))]


# A page's publish time is a fact about its address, so it is kept per address: read once, whichever
# market found it. date_checked marks an address that was read, with or without a time on the page.

def undated_urls(db, limit: int) -> list[str]:
    """Addresses of shown articles whose publish time has not been looked up yet, newest first."""
    return [r["url"] for r in db.execute(
        "SELECT url FROM ticks WHERE kind = 'article' AND hidden = 0 AND published_ts IS NULL AND date_checked = 0"
        " AND url IS NOT NULL GROUP BY url ORDER BY MAX(ts) DESC LIMIT ?", (limit,))]


def date_known(db, url: str) -> tuple[float | None] | None:
    """(publish time or None) if this address was already read under any market; None if it never was."""
    row = db.execute("SELECT published_ts FROM ticks WHERE url = ? AND (published_ts IS NOT NULL OR date_checked = 1)"
                     " ORDER BY published_ts IS NULL LIMIT 1", (url,)).fetchone()
    return row and (row["published_ts"],)


def set_published(db, url: str, ts: float | None) -> list[dict]:
    """Record what reading an address found, on every tick that has it. Returns the shown ticks that gained a time."""
    gained = [] if ts is None else [r["id"] for r in db.execute(
        "SELECT id FROM ticks WHERE url = ? AND published_ts IS NULL AND hidden = 0", (url,))]
    # a page more than a day older than the moment it was found is history, not a live tick
    db.execute("UPDATE ticks SET published_ts = COALESCE(published_ts, ?), date_checked = 1,"
               " backfill = backfill OR COALESCE(COALESCE(published_ts, ?) < ts - 86400, 0) WHERE url = ?", (ts, ts, url))
    return [_tick(db.execute("SELECT * FROM ticks WHERE id = ?", (id,)).fetchone()) for id in gained]


def sources(db, market_id: str, limit: int = 20) -> list[dict]:
    """Where a market's shown ticks came from, and how many of each source's ticks called a move."""
    return [dict(r) for r in db.execute(
        "SELECT source, COUNT(*) AS ticks, SUM(verdict IN ('up', 'down')) AS moved FROM ticks"
        " WHERE market_id = ? AND hidden = 0 GROUP BY source ORDER BY ticks DESC, source LIMIT ?", (market_id, limit))]


def subreddits(db, market_id: str, limit: int = 3) -> list[str]:
    """Subreddits whose posts were shown on this market, most shown first: where to watch for new ones."""
    return [r["source"].removeprefix("reddit.com/r/") for r in db.execute(
        "SELECT source FROM ticks WHERE market_id = ? AND kind = 'post' AND hidden = 0 AND source LIKE 'reddit.com/r/%'"
        " GROUP BY source ORDER BY COUNT(*) DESC, source LIMIT ?", (market_id, limit))]


def headlines(db, market_id: str, limit: int = 20) -> list[str]:
    """Headlines of a market's ticks from the web (not spoken or typed), strongest first, hidden ones
    included: its coverage in brief."""
    return [r["headline"] for r in db.execute(
        "SELECT headline FROM ticks WHERE market_id = ? AND test = 0 ORDER BY ABS(strength) DESC, id LIMIT ?",
        (market_id, limit))]


def count_shown(db, market_id: str, since: float) -> int:
    return db.execute("SELECT COUNT(*) FROM ticks WHERE market_id = ? AND hidden = 0 AND ts >= ?",
                      (market_id, since)).fetchone()[0]
