import pytest

from terminal import googlenews, posts, watch
from terminal.venues import kalshi, polymarket


@pytest.fixture(autouse=True)
def no_post_lookups_over_the_network(monkeypatch):
    """A test that reaches X, Reddit, Google News or the writing model fails loudly: it must pass its own stand-ins.
    A venue's price history is asked for whenever a market is tracked, so it answers "none" unless a test says otherwise."""
    async def x_post(url):
        raise AssertionError(f"test looked up {url} on X")

    async def get_feed(sub):
        raise AssertionError(f"test read r/{sub} from Reddit")

    async def ask_json(prompt):
        raise AssertionError("test asked the writing model")

    async def google(params):
        raise AssertionError("test read Google News")

    monkeypatch.setattr(polymarket, "history", lambda token: [])
    monkeypatch.setattr(kalshi, "history", lambda ticker: [])
    monkeypatch.setattr(kalshi, "search", lambda words: [])  # asked on every question in plain words
    monkeypatch.setattr(googlenews, "_get", google)
    monkeypatch.setattr(watch, "ask_json", ask_json)
    monkeypatch.setattr(posts, "x_post", x_post)
    monkeypatch.setattr(posts, "_get_feed", get_feed)
    monkeypatch.setattr(posts, "_feeds", {})
    monkeypatch.setattr(posts, "_next_feed", 0.0)
