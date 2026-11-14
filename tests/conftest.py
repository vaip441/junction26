import pytest

from terminal import posts, watch


@pytest.fixture(autouse=True)
def no_post_lookups_over_the_network(monkeypatch):
    """A test that reaches X, Reddit or the writing model fails loudly: it must pass its own stand-ins."""
    async def x_post(url):
        raise AssertionError(f"test looked up {url} on X")

    async def get_feed(sub):
        raise AssertionError(f"test read r/{sub} from Reddit")

    async def ask_json(prompt):
        raise AssertionError("test asked the writing model")

    monkeypatch.setattr(watch, "ask_json", ask_json)
    monkeypatch.setattr(posts, "x_post", x_post)
    monkeypatch.setattr(posts, "_get_feed", get_feed)
    monkeypatch.setattr(posts, "_feeds", {})
    monkeypatch.setattr(posts, "_next_feed", 0.0)
