"""HTTP interface for the frontend: markets, ticks, prices, and one server-sent-events stream."""
import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from terminal import db as store
from terminal import scoring
from terminal.bus import Bus
from terminal.pipeline import ingest, public
from terminal.seed import DEMO

STATIC = Path(__file__).parent / "static"
DAY = 86400


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


def summary(db, m: dict, now: float) -> dict:
    price, old = store.price_at(db, m["id"], now), store.price_at(db, m["id"], now - DAY)
    return {"id": m["id"], "venue": m["venue"], "title": m["title"], "url": m["url"], "price": price,
            "change_24h": None if price is None or old is None else price - old,
            "ticks_today": store.count_shown(db, m["id"], now - DAY), "made_up": m["venue"] == "made_up",
            "poll_seconds": m["poll_seconds"]}


def detail(db, m: dict, now: float) -> dict:
    return {**summary(db, m, now), "rules": m["rules"], "queries": m["queries"],
            "related": [summary(db, r, now) for r in store.related(db, m["id"])], "pages": []}


def create_app(db_path: str | None = None, scorer=None, poll: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = store.connect(db_path or os.environ.get("DB_PATH", "terminal.db"))
        app.state.db, app.state.bus, app.state.scorer = db, Bus(), scorer or scoring.score
        if store.get_market(db, DEMO["id"]) is None:
            store.add_market(db, id=DEMO["id"], venue="made_up", venue_ref=None, title=DEMO["title"],
                             rules=DEMO["rules"], url=None)
            store.add_price(db, DEMO["id"], time.time(), DEMO["start"])
        yield
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

    @app.post("/markets/{id}/ticks")
    async def add_tick(id: str, body: TickIn):
        m = market_or_404(id)
        tick = await ingest(app.state.db, app.state.bus, app.state.scorer, m, kind=body.kind,
                            source="microphone" if body.kind == "mic" else "typed", headline=body.text)
        if tick is None:
            raise HTTPException(503, "scoring unavailable, try again")
        return public(tick)

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
