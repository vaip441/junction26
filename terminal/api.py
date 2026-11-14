"""HTTP interface for the frontend: markets, ticks, prices, and one server-sent-events stream."""
import asyncio
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from terminal import db as store
from terminal import contextdev, madeup, match, moves, pages, poller, scoring, truth, venues
from terminal.bus import Bus
from terminal.pipeline import ingest, public
from terminal.record import record
from terminal.seed import DEMO

STATIC = Path(__file__).parent / "static"
UI = Path(__file__).parent.parent / "ui" / "dist"  # the real screen, once built (see README)
DAY = 86400
MAX_RELATED = 5  # an event can hold over a hundred contracts; each one costs a price call a minute
MAX_SHOWN = 6  # markets found for a question that are named to the frontend
HISTORY_WAIT = 8  # seconds a new market's answer may wait for the venue's price history; past that it goes without
OTHER_VENUE_ABOVE = 0.2  # how likely the other venue's market must be the same question to be shown beside the match


class TickIn(BaseModel):
    text: str
    kind: Literal["mic", "typed"]

    @field_validator("text")
    @classmethod
    def trimmed(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 500:
            raise ValueError("text must be 1 to 500 characters")
        return v


class MarketIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    poll_seconds: int = Field(900, ge=30, le=86400)


def consensus(db, m: dict, price: float | None, now: float) -> dict | None:
    """The same question on the other venue, side by side: the middle of the two prices and how far apart
    they are. None unless the market has such a twin and both have a price."""
    twin = m["twin_id"] and store.get_market(db, m["twin_id"])
    other = twin and store.price_at(db, twin["id"], now)
    if price is None or other is None:
        return None
    return {"price": (price + other) / 2, "gap": abs(price - other),
            "venues": [{"id": x["id"], "venue": x["venue"], "price": p, "url": x["url"]}
                       for x, p in ((m, price), (twin, other))]}


def summary(db, m: dict, now: float) -> dict:
    price, old = store.price_at(db, m["id"], now), store.price_at(db, m["id"], now - DAY)
    return {"id": m["id"], "venue": m["venue"], "title": m["title"], "url": m["url"], "price": price,
            "consensus": consensus(db, m, price, now),
            "change_24h": None if price is None or old is None else price - old,
            "ticks_today": store.count_shown(db, m["id"], now - DAY), "made_up": m["venue"] == "made_up",
            "poll_seconds": m["poll_seconds"]}


def detail(db, m: dict, now: float) -> dict:
    return {**summary(db, m, now), "rules": m["rules"], "queries": m["queries"], "companies": m["companies"] or [],
            "related": [summary(db, r, now) for r in store.related(db, m["id"])],
            "pages": [pages.public(p) for p in store.pages(db, m["id"]) if p["url"]],
            "sources": store.sources(db, m["id"])}


def create_app(db_path: str | None = None, scorer=None, poll: bool = True, key: str | None = None,
               ui: Path | None = None) -> FastAPI:
    # Every route is `async def`: the store is one sqlite connection, and a plain `def` route would use it
    # from a worker thread while the background loops use it from the event loop.
    key = key if key is not None else os.environ.get("TERMINAL_KEY", "")

    def write_access(x_terminal_key: str = Header("")):
        """Writes cost model calls and Context.dev credits, so a public deployment sets TERMINAL_KEY."""
        if key and not hmac.compare_digest(x_terminal_key.encode(), key.encode()):
            raise HTTPException(401, "missing or wrong X-Terminal-Key header")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if poll and not key:  # polling means a real deployment: never run one with open writes
            raise RuntimeError("TERMINAL_KEY is not set; refusing to start with writes open to anyone")
        db = store.connect(db_path or os.environ.get("DB_PATH", "terminal.db"))
        app.state.db, app.state.bus, app.state.scorer = db, Bus(), scorer or scoring.score
        if store.get_market(db, DEMO["id"]) is None:
            store.add_market(db, id=DEMO["id"], venue="made_up", venue_ref=None, title=DEMO["title"],
                             rules=DEMO["rules"], url=None)
            store.add_price(db, DEMO["id"], time.time(), DEMO["start"])
        store.set_poll_seconds(db, DEMO["id"], 0)  # it moves only by what is said to it, never by articles
        app.state.wake = asyncio.Event()
        app.state.asked = {}  # words asked -> the venue market they matched, so asking again is instant and stable
        busy = set()  # markets being searched right now, by the article loop or behind a price move
        # Context.dev can only call back an address the internet can reach: no PUBLIC_URL, no page watching
        public_url = os.environ.get("PUBLIC_URL", "")
        watch_page = (lambda db, m: pages.watch(db, m, public_url)) if public_url else None
        tasks = [asyncio.create_task(poller.price_loop(db, app.state.bus, app.state.scorer, busy)),
                 asyncio.create_task(poller.article_loop(db, app.state.bus, app.state.scorer, app.state.wake, busy,
                                                         watch_page)),
                 asyncio.create_task(poller.date_loop(db, app.state.bus))] if poll else []
        if poll and os.environ.get("TRUTH_FEED"):  # the feed file of trump-social-scraper, where one runs
            tasks.append(asyncio.create_task(truth.truth_loop(db, app.state.bus, app.state.scorer, os.environ["TRUTH_FEED"])))
        app.state.tasks = tasks
        yield
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        db.close()

    app = FastAPI(title="Prediction market terminal", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def market_or_404(id: str) -> dict:
        m = store.get_market(app.state.db, id)
        if m is None:
            raise HTTPException(404, "no such market")
        return m

    @app.get("/markets")
    async def markets():
        now = time.time()
        return [summary(app.state.db, m, now) for m in store.list_markets(app.state.db)]

    @app.get("/markets/{id}")
    async def market(id: str):
        return detail(app.state.db, market_or_404(id), time.time())

    @app.delete("/markets/{id}", dependencies=[Depends(write_access)])
    async def delete_market(id: str):
        """Stop tracking a market: it, its related contracts, and their ticks and prices are removed."""
        m = market_or_404(id)
        if id == DEMO["id"]:
            raise HTTPException(409, "the demo market cannot be deleted")
        if m["lead_id"] is not None:
            raise HTTPException(404, "no such market")  # a related contract goes with its lead market
        await pages.unwatch(app.state.db, id)
        store.delete_market(app.state.db, id)
        app.state.bus.publish("market", {"market_id": id, "status": "deleted"})
        return {"deleted": id}

    @app.post("/markets/{id}/reset", dependencies=[Depends(write_access)])
    async def reset(id: str):
        """Put the demo market back to its starting price with an empty tape, after a rehearsal."""
        m = market_or_404(id)
        if id != DEMO["id"]:
            raise HTTPException(409, "only the demo market can be reset")
        now = time.time()
        store.reset_market(app.state.db, id, now, DEMO["start"])
        app.state.bus.publish("market", {"market_id": id, "status": "reset"})
        app.state.bus.publish("price", {"market_id": id, "ts": now, "price": DEMO["start"]})
        return detail(app.state.db, m, now)

    @app.get("/markets/{id}/ticks")
    async def ticks(id: str, limit: int = Query(100, ge=1, le=500)):
        market_or_404(id)
        return [public(t) for t in store.ticks(app.state.db, id, limit)]

    @app.get("/markets/{id}/prices")
    async def prices(id: str, since: float = 0):
        market_or_404(id)
        return store.prices(app.state.db, id, since)

    @app.get("/markets/{id}/moves")
    async def price_moves(id: str, limit: int = Query(20, ge=1, le=100)):
        """The market's price jumps, newest first, each with the tick named as its cause (or null)."""
        market_or_404(id)
        return [moves.public_move(m) for m in store.moves(app.state.db, id, limit)]

    @app.post("/markets/{id}/why", dependencies=[Depends(write_access)])
    async def why(id: str):
        """Why did this market move over the last day? Answers with a move, in about a second."""
        move = await moves.why(app.state.db, app.state.bus, market_or_404(id))
        if move is None:
            raise HTTPException(409, "the price has not moved a point in the last day")
        return move

    @app.post("/markets/{id}/pair", dependencies=[Depends(write_access)])
    async def pair(id: str):
        """Look for the same question on the other venue; when it is there, the two prices become one consensus."""
        m = market_or_404(id)
        if m["venue"] == "made_up":
            raise HTTPException(409, "a made-up market is on no venue")
        try:
            twin = await match.twin(m, await match.candidates(m["title"]))
        except match.SearchFailed:
            raise HTTPException(502, "could not reach search, try again")
        except scoring.ScoringError:
            raise HTTPException(503, "scoring unavailable, try again")
        if twin is not None:
            await with_history(keep_twin(m, twin))
        return detail(app.state.db, store.get_market(app.state.db, id), time.time())

    @app.post("/markets/{id}/ticks", dependencies=[Depends(write_access)])
    async def add_tick(id: str, body: TickIn):
        m = market_or_404(id)
        if m["venue"] == "made_up" and store.latest_price(app.state.db, id) is None:
            raise HTTPException(409, "this market is still opening, try again in a moment")
        tick = await ingest(app.state.db, app.state.bus, app.state.scorer, m, kind=body.kind,
                            source="microphone" if body.kind == "mic" else "typed", headline=body.text)
        if tick is None:
            raise HTTPException(503, "scoring unavailable, try again")
        return public(tick)

    async def with_history(ids: list[str]) -> None:
        """Fill in the last week of prices for markets tracked just now, so the chart is not empty and the
        news found for them has a price to stand on. Venue trouble or a slow answer leaves them as they are."""
        db = app.state.db
        markets = [m for m in (store.get_market(db, id) for id in ids) if m is not None]
        try:
            found = await asyncio.wait_for(asyncio.gather(*(venues.history(m) for m in markets)), HISTORY_WAIT)
        except TimeoutError:
            return
        for m, points in zip(markets, found):
            if store.get_market(db, m["id"]) is not None:  # deleted meanwhile
                store.add_history(db, m["id"], points)

    def track(contracts: list[dict], extra: list[dict], poll_seconds: int) -> tuple[str, list[str]]:
        """Store a lead contract with its related ones, unless it is already tracked. Returns the lead's id
        and the ids of the markets stored just now, which have no price history yet."""
        db, lead, now, fresh = app.state.db, contracts[0], time.time(), []
        lead_id = venues.market_id(lead)
        existing = store.get_market(db, lead_id)
        if existing is not None and existing["lead_id"] is None:
            return lead_id, fresh
        if existing is not None:
            store.promote(db, lead_id)  # a related contract asked for by itself becomes a market
        else:
            for c in contracts[:1 + MAX_RELATED] + extra:
                fresh.append(keep(c, None if c is lead else lead_id, poll_seconds, now))
        app.state.bus.publish("market", {"market_id": lead_id, "status": "tracking"})
        return lead_id, fresh

    def keep(c: dict, lead_id: str | None, poll_seconds: int, now: float) -> str:
        db, id = app.state.db, venues.market_id(c)
        store.add_market(db, id=id, venue=c["venue"], venue_ref=c["venue_ref"], title=c["title"],
                         rules=c["rules"], url=c["url"], lead_id=lead_id, poll_seconds=poll_seconds)
        if c["price"] is not None:
            store.add_price(db, id, now, c["price"])
        return id

    def keep_twin(m: dict, twin: dict) -> list[str]:
        """Pair a market with the contract that asks the same thing on the other venue, storing that contract
        beside it unless it is tracked already. Returns the ids stored just now."""
        db, id = app.state.db, venues.market_id(twin)
        fresh = [] if store.get_market(db, id) else [keep(twin, m["lead_id"] or m["id"], m["poll_seconds"], time.time())]
        store.pair(db, m["id"], id)
        return fresh

    async def from_words(words: str, poll_seconds: int) -> tuple[str, bool, list[str]]:
        """Plain words -> (id of the market now tracked, whether a venue contract matched, markets stored just now)."""
        db, bus = app.state.db, app.state.bus
        made_id = madeup.market_id(words)
        if store.get_market(db, app.state.asked.get(made_id, "")) is not None:
            return app.state.asked[made_id], True, []

        def status(text: str, **more) -> None:
            bus.publish("market", {"market_id": None, "query": words, "status": text, **more})

        def fail(code: int, text: str):
            status("failed")
            return HTTPException(code, text)

        status("searching venues")
        try:
            groups = await match.candidates(words)
            # one card per market found, for the frontend to show while the model picks
            status("found contracts", count=len(groups),
                   contracts=[{"venue": g[0]["venue"], "title": g[0]["event"], "price": g[0]["price"], "contracts": len(g)}
                              for g in groups[:MAX_SHOWN]])
            winner, probs, leads = await match.pick(words, groups)
            # words asked before that found no market keep their made-up one, unless a real one now exists
            made = store.get_market(db, made_id)
            question = await madeup.question_for(words, date.today()) if winner is None and made is None else None
        except match.SearchFailed:
            raise fail(502, "could not reach search, try again")
        except scoring.ScoringError:
            raise fail(503, "scoring unavailable, try again")
        except madeup.WritingFailed:
            raise fail(502, "could not reach the writing model, try again")
        except madeup.NotAQuestion:
            raise fail(422, "that does not look like a question about something that could happen")
        if winner is None:
            if made is None:  # no price yet: the article loop sets the starting odds from the coverage it finds
                store.add_market(db, id=made_id, venue="made_up", venue_ref=None, title=question["title"],
                                 rules=question["rules"], url=None, poll_seconds=poll_seconds)
            bus.publish("market", {"market_id": made_id, "query": words, "status": "made up"})
            return made_id, False, []
        contracts = groups[winner]
        contracts.insert(0, contracts.pop(leads[winner]))  # the contract the question names leads
        status("picked", winner=winner, venue=contracts[0]["venue"], title=contracts[0]["title"], price=contracts[0]["price"])
        try:
            twin = await match.twin(contracts[0], groups)
        except scoring.ScoringError:
            twin = None  # the market is worth tracking without its other venue; POST /markets/{id}/pair asks again
        # beside the match: the other venue's market when it is close, as the contract asking the very same thing if one does
        other = [twin if twin in g else g[leads[i]] for i, g in enumerate(groups)
                 if i != winner and (probs[i] >= OTHER_VENUE_ABOVE or twin in g) and g[0]["venue"] != contracts[0]["venue"]]
        app.state.asked[made_id], fresh = track(contracts, other, poll_seconds)
        if twin is not None:
            fresh += keep_twin(store.get_market(db, app.state.asked[made_id]), twin)
        return app.state.asked[made_id], True, fresh

    @app.post("/markets", dependencies=[Depends(write_access)])
    async def add_market(body: MarketIn):
        """Track a market from a Kalshi or Polymarket link, or from a question in plain words."""
        try:
            (lead_id, fresh), matched = track(await venues.resolve(body.query), [], body.poll_seconds), True
        except venues.NotAVenueLink:
            lead_id, matched, fresh = await from_words(body.query, body.poll_seconds)
        except venues.MarketNotFound as e:
            raise HTTPException(404, str(e))
        except venues.VenueError as e:
            raise HTTPException(502, f"the venue did not answer properly, try again ({e})")
        await with_history(fresh)  # before the answer, so the first chart the frontend draws has it
        app.state.wake.set()  # the article loop writes the queries and does the instant fill
        db = app.state.db
        return {**detail(db, store.get_market(db, lead_id), time.time()), "matched": matched}

    @app.post("/hooks/context/{page_id}", include_in_schema=False)
    async def context_hook(page_id: str, request: Request):
        """Context.dev calls this after each check of a watched page. Nothing is believed, or even parsed,
        before the signature made with that page's secret checks out."""
        raw, page = await request.body(), store.get_page(app.state.db, page_id)
        if page is None or not pages.verify(raw, request.headers.get("x-context-signature", ""), page["secret"] or ""):
            raise HTTPException(401, "bad signature")  # the same answer for an unknown page: nothing to probe
        try:
            event = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "not JSON")
        if not await pages.delivered(app.state.db, app.state.bus, app.state.scorer, page, event):
            raise HTTPException(503, "could not score the change, deliver it again")
        return {"ok": True}

    @app.get("/status")
    async def status():
        """How much Context.dev capacity the key pool has and is using. Keys are numbered, never shown."""
        return {"context_dev": contextdev.status()}

    @app.get("/record")
    async def weekend_record():
        return record(app.state.db)

    @app.get("/stream")
    async def stream(request: Request):
        bus = app.state.bus

        async def events():
            q = bus.subscribe()
            try:
                yield ": connected\n\n"
                while bus.alive(q) and not await request.is_disconnected():
                    try:
                        event, data = await asyncio.wait_for(q.get(), 15)
                        yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/debug", include_in_schema=False)
    async def debug_page():
        return FileResponse(STATIC / "debug.html")

    if ui is not None and (ui / "index.html").is_file():
        app.mount("/", StaticFiles(directory=ui, html=True))  # last, so every route above answers first
    else:  # the screen has not been built on this machine
        app.get("/", include_in_schema=False)(debug_page)

    return app


app = create_app(ui=UI)
