"""SQLite store: markets (related contracts are rows pointing at their lead market), ticks, prices, moves,
watched pages.

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
CREATE TABLE IF NOT EXISTS moves (
    id INTEGER PRIMARY KEY, market_id TEXT NOT NULL, ts REAL NOT NULL, since_ts REAL NOT NULL,
    from_price REAL NOT NULL, to_price REAL NOT NULL, tick_id INTEGER, confidence REAL, rule TEXT,
    explained INTEGER NOT NULL DEFAULT 0, related TEXT NOT NULL DEFAULT '[]', asked INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS moves_by_market ON moves (market_id, ts);
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY, market_id TEXT NOT NULL, url TEXT, title TEXT, monitor_id TEXT, secret TEXT,
    created_ts REAL NOT NULL, checked_ts REAL, changed_ts REAL);
CREATE INDEX IF NOT EXISTS pages_by_market ON pages (market_id);
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
    if "explained" not in {r["name"] for r in db.execute("PRAGMA table_info(moves)")}:  # stores from before 14 Nov 12:00
        db.execute("ALTER TABLE moves ADD COLUMN explained INTEGER NOT NULL DEFAULT 0")
        db.execute("ALTER TABLE moves ADD COLUMN related TEXT NOT NULL DEFAULT '[]'")
        db.execute("ALTER TABLE moves ADD COLUMN asked INTEGER NOT NULL DEFAULT 0")
        db.execute("UPDATE moves SET explained = tick_id IS NOT NULL")  # until then a tick was stored only as a cause
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
    """Remove a market, its related contracts, and all their ticks, prices and moves."""
    for (mid,) in db.execute("SELECT id FROM markets WHERE id = ? OR lead_id = ?", (id, id)).fetchall():
        db.execute("DELETE FROM ticks WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM moves WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM pages WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM prices WHERE market_id = ?", (mid,))
        db.execute("DELETE FROM markets WHERE id = ?", (mid,))


def reset_market(db, id: str, ts: float, price: float) -> None:
    """Forget everything that happened on a market and start it again at a price."""
    for table in ("ticks", "prices", "moves"):
        db.execute(f"DELETE FROM {table} WHERE market_id = ?", (id,))
    add_price(db, id, ts, price)


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


def has_title(db, market_id: str, title_key: str, since: float) -> bool:
    """Whether this market got an article with this headline, from any outlet or address, since a time."""
    return db.execute("SELECT 1 FROM ticks WHERE market_id = ? AND title_key = ? AND ts >= ?",
                      (market_id, title_key, since)).fetchone() is not None


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


def around(db, market_id: str, since: float, until: float, limit: int, strongest: bool = False) -> list[dict]:
    """A market's shown, live ticks from the web published in a stretch of time (found, where the publish
    time is unknown): what could explain a price move at its end. Newest first, or strongest first."""
    order = "ABS(strength) DESC" if strongest else "COALESCE(published_ts, ts) DESC"
    return [_tick(r) for r in db.execute(
        "SELECT * FROM ticks WHERE market_id = ? AND hidden = 0 AND test = 0 AND backfill = 0"
        f" AND COALESCE(published_ts, ts) BETWEEN ? AND ? ORDER BY {order}, id DESC LIMIT ?",
        (market_id, since, until, limit))]


def add_move(db, market_id: str, ts: float, since: float, from_price: float, to_price: float, tick_id: int | None,
             confidence: float | None, rule: str | None, explained: bool, related: list, asked: bool = False) -> dict:
    """A price move with the tick nearest to explaining it (if any), whether that tick is taken as the cause,
    and the related contracts that moved with it. `asked`: explained on request, not seen as a jump."""
    cur = db.execute("INSERT INTO moves (market_id, ts, since_ts, from_price, to_price, tick_id, confidence, rule,"
                     " explained, related, asked) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (market_id, ts, since, from_price, to_price, tick_id, confidence, rule, explained,
                      json.dumps(related), asked))
    return next(m for m in moves(db, market_id, limit=1000) if m["id"] == cur.lastrowid)


def moves(db, market_id: str, limit: int = 20) -> list[dict]:
    """A market's price moves, newest first, each with its tick (or None) under "tick"."""
    out = []
    for r in db.execute('SELECT id, market_id, ts, since_ts AS since, from_price AS "from", to_price AS "to", tick_id,'
                        " confidence, rule, explained, related, asked FROM moves WHERE market_id = ?"
                        " ORDER BY ts DESC, id DESC LIMIT ?", (market_id, limit)).fetchall():
        tick = db.execute("SELECT * FROM ticks WHERE id = ?", (r["tick_id"],)).fetchone()
        out.append({**{k: r[k] for k in r.keys() if k != "tick_id"}, "rule": r["rule"] and json.loads(r["rule"]),
                    "explained": bool(r["explained"]), "asked": bool(r["asked"]), "related": json.loads(r["related"]),
                    "tick": tick and _tick(tick)})
    return out


def last_move(db, market_id: str) -> float | None:
    """When this market's newest jump was recorded (moves explained on request do not count)."""
    return db.execute("SELECT MAX(ts) FROM moves WHERE market_id = ? AND asked = 0", (market_id,)).fetchone()[0]


# A watched page: `id` is the unguessable last part of its webhook address, `secret` signs its deliveries.
# A row without a url records that the market was looked at and has no page worth watching.

def add_page(db, id: str, market_id: str, url: str | None, title: str | None, monitor_id: str | None,
             secret: str | None, ts: float) -> dict:
    db.execute("INSERT INTO pages (id, market_id, url, title, monitor_id, secret, created_ts) VALUES (?,?,?,?,?,?,?)",
               (id, market_id, url, title, monitor_id, secret, ts))
    return get_page(db, id)


def get_page(db, id: str) -> dict | None:
    row = db.execute("SELECT * FROM pages WHERE id = ?", (id,)).fetchone()
    return row and dict(row)


def pages(db, market_id: str) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM pages WHERE market_id = ? ORDER BY created_ts, id", (market_id,))]


def forget_unwatched(db, market_id: str) -> None:
    """Drop the record that a market had no page worth watching, before it is looked at again."""
    db.execute("DELETE FROM pages WHERE market_id = ? AND url IS NULL", (market_id,))


def page_checked(db, id: str, ts: float, changed: bool) -> None:
    db.execute("UPDATE pages SET checked_ts = ?, changed_ts = CASE WHEN ? THEN ? ELSE changed_ts END WHERE id = ?",
               (ts, changed, ts, id))
