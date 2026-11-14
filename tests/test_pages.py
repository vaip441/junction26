import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from terminal import db as store
from terminal import pages
from terminal.api import create_app
from terminal.bus import Bus
from terminal.scoring import Score, ScoringError

NOW = 1_800_000_000.0
MARKET = {"id": "m", "title": "Will Ann Lee be the next CEO of Acme?",
          "rules": "Resolves Yes if Acme announces Ann Lee as CEO.\nInterim CEOs will not qualify."}
RESULTS = [{"url": "https://news.acme.example/one-release", "title": "Acme names interim CEO", "description": "", "text": ""},
           {"url": "https://news.acme.example/", "title": "Acme Newsroom", "description": "", "text": ""}]


async def up(*_):
    return Score(0.84, 0.12, 0.04, 0.8)


async def down_for_now(*_):
    raise ScoringError("api down")


def finder(probabilities, results=RESULTS, seen=None):
    async def ask(prompt):
        return ["Acme newsroom press releases"]

    async def search(query, **kw):
        if seen is not None:
            seen.append((query, kw))
        return results

    async def decide(input, questions):
        if seen is not None:
            seen.append(questions)
        return {"page": {"probabilities": probabilities}}

    return {"ask": ask, "search": search, "decide": decide}


def test_the_page_to_watch_is_found_on_the_live_web_and_chosen_by_decision_1():
    seen = []
    page = asyncio.run(pages.find(MARKET, **finder({"p0": 0.2, "p1": 0.7, "none": 0.1}, seen=seen)))
    assert page == {"url": "https://news.acme.example/", "title": "Acme Newsroom"}
    (query, kw), questions = seen
    assert query == "Acme newsroom press releases" and kw["freshness"] is None  # an old page is the point
    assert "polymarket.com" in kw["exclude_domains"] and "x.com" in kw["exclude_domains"]
    assert questions["page"]["type"] == "choice" and list(questions["page"]["criteria"]) == ["p0", "p1", "none"]
    assert "https://news.acme.example/" in questions["page"]["criteria"]["p1"]


def test_no_page_is_watched_when_none_of_them_is_likelier_and_a_failing_step_is_an_error():
    find = lambda **kw: asyncio.run(pages.find(MARKET, **kw))
    assert find(**finder({"p0": 0.4, "none": 0.6})) is None
    assert find(**finder({"p0": 0.3, "p1": 0.3, "none": 0.3})) is None
    # several good pages split the vote (seen live: three UEFA pages at 0.31, 0.21, 0.16, none at 0.04): take the best
    assert find(**finder({"p0": 0.16, "p1": 0.31, "none": 0.04}))["url"] == "https://news.acme.example/"
    assert find(**finder({}, results=[])) is None  # nothing found: nothing to ask
    with pytest.raises(ScoringError):
        find(**finder({"p9": 0.9}))


def signed(raw: bytes, secret: str, ts: float = NOW) -> str:
    return f"t={int(ts)},v1=" + hmac.new(secret.encode(), f"{int(ts)}.".encode() + raw, hashlib.sha256).hexdigest()


def test_a_webhook_is_believed_only_with_a_fresh_signature_over_the_exact_body():
    raw = b'{"event": "change.detected"}'
    assert pages.verify(raw, signed(raw, "whsec_a"), "whsec_a", now=NOW)
    assert pages.verify(raw, signed(raw, "whsec_a").upper().replace("T=", "t=").replace("V1=", "v1="), "whsec_a", now=NOW)
    assert not pages.verify(raw + b" ", signed(raw, "whsec_a"), "whsec_a", now=NOW)        # another body
    assert not pages.verify(raw, signed(raw, "whsec_b"), "whsec_a", now=NOW)               # another secret
    assert not pages.verify(raw, signed(raw, "whsec_a", NOW - 301), "whsec_a", now=NOW)    # replayed later
    for odd in ("", "v1=abc", "t=1,t=2,v1=" + "a" * 64, "t=x,v1=" + "a" * 64, "nonsense"):
        assert not pages.verify(raw, odd, "whsec_a", now=NOW)


def market(db, id="m"):
    return store.add_market(db, id=id, venue="kalshi", venue_ref=id, title=MARKET["title"], rules=MARKET["rules"],
                            url=None, queries=["acme ceo"])


def test_watching_a_market_creates_a_monitor_whose_webhook_is_this_markets_own_address():
    db, made = store.connect(":memory:"), []
    m = market(db)

    async def find(market):
        return {"url": "https://news.acme.example/", "title": "Acme Newsroom"}

    async def create(url, instructions, hook, name):
        made.append((url, instructions, hook, name))
        return {"id": "mon_1", "secret": "whsec_a"}

    page = asyncio.run(pages.watch(db, m, "https://terminal.example/", find=find, create=create, now=NOW))
    [(url, instructions, hook, name)] = made
    assert url == "https://news.acme.example/" and "Will Ann Lee be the next CEO of Acme?" in instructions
    assert "Interim CEOs will not qualify" in instructions and "\n" not in instructions
    assert hook == f"https://terminal.example/hooks/context/{page['id']}" and len(page["id"]) >= 20  # not guessable
    assert store.pages(db, "m") == [page] and store.get_page(db, page["id"])["secret"] == "whsec_a"
    assert (page["monitor_id"], page["checked_ts"], page["changed_ts"]) == ("mon_1", None, None)


def test_a_market_with_no_page_worth_watching_is_remembered_and_a_failed_monitor_is_not():
    db = store.connect(":memory:")
    m = market(db)

    async def nothing(market):
        return None

    async def found(market):
        return {"url": "https://news.acme.example/", "title": "Acme Newsroom"}

    async def refused(url, instructions, hook, name):
        raise RuntimeError("no credits")

    with pytest.raises(RuntimeError):
        asyncio.run(pages.watch(db, m, "https://t.example", find=found, create=refused))
    assert store.pages(db, "m") == []  # tried again on the next pass
    assert asyncio.run(pages.watch(db, m, "https://t.example", find=nothing, create=refused, now=NOW)) is None
    [row] = store.pages(db, "m")
    assert row["url"] is None and row["monitor_id"] is None  # looked for, nothing found: remembered

    async def create(url, instructions, hook, name):
        return {"id": "mon_1", "secret": "whsec_a"}

    page = asyncio.run(pages.watch(db, m, "https://t.example", find=found, create=create, now=NOW + 86400))
    assert store.pages(db, "m") == [page] and page["url"]  # found on a later look: the empty record is gone


def watched(db):
    return store.add_page(db, "tok", "m", "https://news.acme.example/", "Acme Newsroom", "mon_1", "whsec_a", NOW - 900)


CHANGE = {"event": "change.detected", "id": "evt_1", "data": {"change": {
    "id": "chg_1", "monitor_id": "mon_1", "title": "Acme Newsroom changed",
    "summary": "The page now lists a release naming Ann Lee as chief executive.", "detected_at": "2027-01-15T08:00:00Z",
    "confidence": 0.9, "after_text_excerpt": "Acme names Ann Lee CEO"}}}
QUIET = {"event": "run.completed", "id": "evt_0", "data": {"run": {"id": "run_1"}, "change": None}}


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_a_change_on_a_watched_page_becomes_a_tick_once_and_every_check_is_announced():
    db, bus = store.connect(":memory:"), Bus()
    market(db)
    page, q = watched(db), bus.subscribe()
    assert asyncio.run(pages.delivered(db, bus, up, page, QUIET, now=NOW)) is True
    assert drain(q) == [("page_check", {"market_id": "m", "url": "https://news.acme.example/", "ts": NOW, "changed": False})]
    assert store.pages(db, "m")[0]["checked_ts"] == NOW and store.pages(db, "m")[0]["changed_ts"] is None

    assert asyncio.run(pages.delivered(db, bus, up, page, CHANGE, now=NOW + 600)) is True
    check, (event, tick) = drain(q)
    assert check[1]["changed"] is True and event == "tick"
    assert (tick["kind"], tick["source"], tick["url"], tick["verdict"]) == ("page", "news.acme.example", "https://news.acme.example/", "up")
    assert tick["headline"] == "The page now lists a release naming Ann Lee as chief executive."
    assert tick["published_ts"] == 1800000000.0 and store.pages(db, "m")[0]["changed_ts"] == NOW + 600
    # the same change delivered again (a retry, or run.completed carrying it) is not a second tick
    again = {"event": "run.completed", "id": "evt_2", "data": {"run": {}, "change": CHANGE["data"]["change"]}}
    assert asyncio.run(pages.delivered(db, bus, up, page, again, now=NOW + 601)) is True
    assert len(store.ticks(db, "m")) == 1
    # a later change of the same page is a new tick
    later = json.loads(json.dumps(CHANGE))
    later["data"]["change"]["id"] = "chg_2"
    assert asyncio.run(pages.delivered(db, bus, up, page, later, now=NOW + 1200)) is True
    assert len(store.ticks(db, "m")) == 2


def test_a_change_that_cannot_be_scored_right_now_is_asked_for_again_and_odd_events_are_only_checks():
    db, bus = store.connect(":memory:"), Bus()
    market(db)
    page = watched(db)
    assert asyncio.run(pages.delivered(db, bus, down_for_now, page, CHANGE, now=NOW)) is False  # Context.dev retries
    assert store.ticks(db, "m") == []
    for odd in ({}, {"data": None}, {"data": {"change": "yes"}}, {"data": {"change": {"summary": "no id"}}}, []):
        assert asyncio.run(pages.delivered(db, bus, up, page, odd, now=NOW)) is True
    assert store.ticks(db, "m") == []
    store.delete_market(db, "m")
    assert asyncio.run(pages.delivered(db, bus, up, page, CHANGE, now=NOW)) is True  # nothing left to tell


def test_the_hook_refuses_unsigned_calls_and_the_market_shows_its_page_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(pages.time, "time", lambda: NOW)
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), scorer=up, poll=False)) as c:
        db = c.app.state.db
        market(db)
        watched(db)
        store.add_page(db, "none", "m", None, None, None, None, NOW)  # looked for, nothing found: not shown
        raw = json.dumps(CHANGE).encode()
        post = lambda path, sig: c.post(path, content=raw, headers={"X-Context-Signature": sig, "content-type": "application/json"})
        assert post("/hooks/context/tok", signed(raw, "wrong")).status_code == 401
        assert post("/hooks/context/unknown", signed(raw, "whsec_a")).status_code == 401
        assert post("/hooks/context/none", signed(raw, "")).status_code == 401
        assert c.post("/hooks/context/tok", content=raw).status_code == 401
        assert c.get("/markets/m/ticks").json() == []
        assert post("/hooks/context/tok", signed(raw, "whsec_a")).status_code == 200
        assert [t["kind"] for t in c.get("/markets/m/ticks").json()] == ["page"]
        bad = b"not json"
        assert c.post("/hooks/context/tok", content=bad, headers={"X-Context-Signature": signed(bad, "whsec_a")}).status_code == 400
        detail = c.get("/markets/m").json()
    assert detail["pages"] == [{"url": "https://news.acme.example/", "title": "Acme Newsroom",
                                "checked_ts": NOW, "changed_ts": NOW}]


def test_a_deleted_market_stops_its_monitor(tmp_path, monkeypatch):
    stopped = []

    async def delete_monitor(id):
        stopped.append(id)
        return True

    monkeypatch.setattr(pages.contextdev, "delete_monitor", delete_monitor)
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), scorer=up, poll=False)) as c:
        db = c.app.state.db
        market(db)
        watched(db)
        store.add_page(db, "none", "m", None, None, None, None, NOW)
        assert c.delete("/markets/m").status_code == 200
        assert stopped == ["mon_1"] and store.pages(db, "m") == [] and store.get_page(db, "tok") is None
