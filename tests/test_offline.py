"""The offline replay demo: the real backend with the bundled replays, no key and no network."""
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from terminal.api import REPLAYS, create_app


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to reach another machine fails the test, and no key is in the environment."""
    for name in ("GEMINI_API_KEY", "CONTEXT_DEV_API_KEY", "TERMINAL_KEY", "PUBLIC_URL", "TRUTH_FEED"):
        monkeypatch.delenv(name, raising=False)

    def refuse(*a, **kw):
        raise AssertionError("the offline demo tried to open a connection")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def offline(tmp_path):
    return TestClient(create_app(db_path=str(tmp_path / "demo.db"), offline=True, key="", replays=REPLAYS))


def test_the_offline_demo_starts_without_keys_and_serves_the_bundled_replays(tmp_path, no_network):
    with offline(tmp_path) as c:
        assert c.app.state.tasks == []  # nothing polls
        markets = c.get("/markets").json()
        replays = [m for m in markets if m["replay"]]
        assert sorted(m["id"] for m in replays) == ["replay-lula", "replay-senate", "replay-texas"]
        for m in replays:
            ticks = c.get(f"/markets/{m['id']}/ticks?limit=500").json()
            assert ticks and all(t["provenance"] == "replay" for t in ticks)  # never passed off as found live
            assert len(c.get(f"/markets/{m['id']}/prices").json()) > 100
            assert c.get(f"/markets/{m['id']}").json()["found_by"][0]["provenance"] == "replay"
        assert c.get("/metrics").json()["mode"] == "offline"
        assert c.get("/metrics").json()["discovery_to_scored"]["median"] is None  # replays are not live latency
        assert c.get("/record").json()["calls"] == 0  # nor part of the live record


def test_offline_nothing_is_scored_searched_or_changed(tmp_path, no_network):
    with offline(tmp_path) as c:
        said = c.post("/markets/mu-demo/ticks", json={"text": "that is clever", "kind": "typed"})
        assert said.status_code == 503 and "offline" in said.json()["detail"]
        assert c.post("/markets", json={"query": "will it rain"}).status_code == 503
        assert c.post("/transcribe", content=b"RIFF", headers={"content-type": "audio/wav"}).status_code == 503
        assert c.post("/markets/replay-lula/why").status_code == 503
        assert c.delete("/markets/replay-lula").status_code == 503
        assert c.get("/markets/mu-demo/ticks").json() == []


def test_the_live_app_is_not_offline(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "t.db"), poll=False, replays=REPLAYS)) as c:
        assert c.get("/metrics").json()["mode"] == "live"
