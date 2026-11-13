"""HTTP interface for the frontend: markets, ticks, prices, and one server-sent-events stream."""
import asyncio
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from terminal import db as store
from terminal import contextdev, poller, scoring, venues
from terminal.bus import Bus
from terminal.pipeline import ingest, public
from terminal.record import record
from terminal.seed import DEMO

STATIC = Path(__file__).parent / "static"
DAY = 86400
MAX_RELATED = 5  # an event can hold over a hundred contracts; each one costs a price call a minute


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


def summary(db, m: dict, now: float) -> dict:
    price, old = store.price_at(db, m["id"], now), store.price_at(db, m["id"], now - DAY)
    return {"id": m["id"], "venue": m["venue"], "title": m["title"], "url": m["url"], "price": price,
            "change_24h": None if price is None or old is None else price - old,
            "ticks_today": store.count_shown(db, m["id"], now - DAY), "made_up": m["venue"] == "made_up",
            "poll_seconds": m["poll_seconds"]}


def detail(db, m: dict, now: float) -> dict:
    return {**summary(db, m, now), "rules": m["rules"], "queries": m["queries"],
            "related": [summary(db, r, now) for r in store.related(db, m["id"])], "pages": []}


def create_app(db_path: str | None = None, scorer=None, poll: bool = True, key: str | None = None) -> FastAPI:
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
        app.state.wake = asyncio.Event()
        tasks = [asyncio.create_task(poller.price_loop(db, app.state.bus)),
                 asyncio.create_task(poller.article_loop(db, app.state.bus, app.state.scorer, app.state.wake))
                 ] if poll else []
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
    def markets():
        now = time.time()
        return [summary(app.state.db, m, now) for m in store.list_markets(app.state.db)]

    @app.get("/markets/{id}")
    def market(id: str):
        return detail(app.state.db, market_or_404(id), time.time())

    @app.get("/markets/{id}/ticks")
    def ticks(id: str, limit: int = Query(100, ge=1, le=500)):
        market_or_404(id)
        return [public(t) for t in store.ticks(app.state.db, id, limit)]

    @app.get("/markets/{id}/prices")
    def prices(id: str, since: float = 0):
        market_or_404(id)
        return store.prices(app.state.db, id, since)

    @app.post("/markets/{id}/ticks", dependencies=[Depends(write_access)])
    async def add_tick(id: str, body: TickIn):
        m = market_or_404(id)
        tick = await ingest(app.state.db, app.state.bus, app.state.scorer, m, kind=body.kind,
                            source="microphone" if body.kind == "mic" else "typed", headline=body.text)
        if tick is None:
            raise HTTPException(503, "scoring unavailable, try again")
        return public(tick)

    @app.post("/markets", dependencies=[Depends(write_access)])
    async def add_market(body: MarketIn):
        db = app.state.db
        try:
            contracts = await venues.resolve(body.query)
        except venues.NotAVenueLink:
            raise HTTPException(422, "paste a Kalshi or Polymarket market link")
        except venues.MarketNotFound as e:
            raise HTTPException(404, str(e))
        except venues.VenueError as e:
            raise HTTPException(502, f"the venue did not answer properly, try again ({e})")
        lead, now = contracts[0], time.time()
        lead_id = venues.market_id(lead)
        existing = store.get_market(db, lead_id)
        if existing is not None and existing["lead_id"] is not None:
            store.promote(db, lead_id)  # a related contract pasted by its own link becomes a market
            app.state.bus.publish("market", {"market_id": lead_id, "status": "tracking"})
        elif existing is None:
            for c in contracts[:1 + MAX_RELATED]:
                id = venues.market_id(c)
                store.add_market(db, id=id, venue=c["venue"], venue_ref=c["venue_ref"], title=c["title"],
                                 rules=c["rules"], url=c["url"], lead_id=None if c is lead else lead_id,
                                 poll_seconds=body.poll_seconds)
                if c["price"] is not None:
                    store.add_price(db, id, now, c["price"])
            app.state.bus.publish("market", {"market_id": lead_id, "status": "tracking"})
        app.state.wake.set()  # the article loop writes the queries and does the instant fill
        return detail(db, store.get_market(db, lead_id), time.time())

    @app.get("/status")
    def status():
        """How much Context.dev capacity the key pool has and is using. Keys are numbered, never shown."""
        return {"context_dev": contextdev.status()}

    @app.get("/record")
    def weekend_record():
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

    @app.get("/", include_in_schema=False)
    def debug_page():
        return FileResponse(STATIC / "debug.html")

    return app


app = create_app()
