"""SQLite store: markets (related contracts are rows pointing at their lead market), ticks, prices.

Prices are percentages 0..100 and timestamps are unix seconds, everywhere.
"""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    id TEXT PRIMARY KEY, venue TEXT NOT NULL, venue_ref TEXT, title TEXT NOT NULL, rules TEXT NOT NULL,
    url TEXT, lead_id TEXT, queries TEXT NOT NULL DEFAULT '[]', poll_seconds INTEGER NOT NULL DEFAULT 900,
    filled INTEGER NOT NULL DEFAULT 0,
    created_ts REAL NOT NULL DEFAULT (unixepoch('subsec')));
CREATE TABLE IF NOT EXISTS prices (
    market_id TEXT NOT NULL, ts REAL NOT NULL, price REAL NOT NULL, PRIMARY KEY (market_id, ts));
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY, market_id TEXT NOT NULL, ts REAL NOT NULL, published_ts REAL, kind TEXT NOT NULL,
    source TEXT NOT NULL, url TEXT, headline TEXT NOT NULL, up REAL NOT NULL, none REAL NOT NULL, down REAL NOT NULL,
    strength REAL NOT NULL, verdict TEXT NOT NULL, confidence REAL NOT NULL, price_at REAL,
    test INTEGER NOT NULL, backfill INTEGER NOT NULL, hidden INTEGER NOT NULL, dedupe_key TEXT NOT NULL,
    UNIQUE (market_id, dedupe_key));
CREATE INDEX IF NOT EXISTS ticks_by_market ON ticks (market_id, ts);
"""
TICK_COLS = ("market_id", "ts", "published_ts", "kind", "source", "url", "headline", "up", "none", "down", "strength",
             "verdict", "confidence", "price_at", "test", "backfill", "hidden", "dedupe_key")


def connect(path: str) -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)  # autocommit: every write is durable
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    if "filled" not in {r["name"] for r in db.execute("PRAGMA table_info(markets)")}:  # stores created before 13 Nov
        db.execute("ALTER TABLE markets ADD COLUMN filled INTEGER NOT NULL DEFAULT 0")
    return db


def _market(row) -> dict | None:
    return row and {**row, "queries": json.loads(row["queries"]), "filled": bool(row["filled"])}


def _tick(row) -> dict:
    return {**row, "test": bool(row["test"]), "backfill": bool(row["backfill"]), "hidden": bool(row["hidden"])}


def add_market(db, *, id, venue, venue_ref, title, rules, url, lead_id=None, queries=(), poll_seconds=900) -> dict:
    db.execute("INSERT OR IGNORE INTO markets (id, venue, venue_ref, title, rules, url, lead_id, queries, poll_seconds)"
               " VALUES (?,?,?,?,?,?,?,?,?)",
               (id, venue, venue_ref, title, rules, url, lead_id, json.dumps(list(queries)), poll_seconds))
    return get_market(db, id)


def set_queries(db, id: str, queries: list[str]) -> None:
    db.execute("UPDATE markets SET queries = ? WHERE id = ?", (json.dumps(queries), id))


def set_filled(db, id: str) -> None:
    """The market's first article pass (its backfill) has completed; later passes are live."""
    db.execute("UPDATE markets SET filled = 1 WHERE id = ?", (id,))


def set_poll_seconds(db, id: str, seconds: int) -> None:
    """0 means the market is never polled for articles."""
    db.execute("UPDATE markets SET poll_seconds = ? WHERE id = ?", (seconds, id))


def promote(db, id: str) -> None:
    """Turn a related contract into a market of its own."""
    db.execute("UPDATE markets SET lead_id = NULL WHERE id = ?", (id,))


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


def add_tick(db, tick: dict) -> dict | None:
    """Store a tick; None if this market already has one with the same dedupe_key."""
    cur = db.execute(f"INSERT OR IGNORE INTO ticks ({', '.join(TICK_COLS)}) VALUES ({', '.join('?' * len(TICK_COLS))})",
                     [tick[c] for c in TICK_COLS])
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


def sources(db, market_id: str, limit: int = 20) -> list[dict]:
    """Where a market's shown ticks came from, and how many of each source's ticks called a move."""
    return [dict(r) for r in db.execute(
        "SELECT source, COUNT(*) AS ticks, SUM(verdict IN ('up', 'down')) AS moved FROM ticks"
        " WHERE market_id = ? AND hidden = 0 GROUP BY source ORDER BY ticks DESC, source LIMIT ?", (market_id, limit))]


def headlines(db, market_id: str, limit: int = 20) -> list[str]:
    """Headlines of a market's ticks from the web (not spoken or typed), strongest first, hidden ones
    included: its coverage in brief."""
    return [r["headline"] for r in db.execute(
        "SELECT headline FROM ticks WHERE market_id = ? AND test = 0 ORDER BY ABS(strength) DESC, id LIMIT ?",
        (market_id, limit))]


def count_shown(db, market_id: str, since: float) -> int:
    return db.execute("SELECT COUNT(*) FROM ticks WHERE market_id = ? AND hidden = 0 AND ts >= ?",
                      (market_id, since)).fetchone()[0]
