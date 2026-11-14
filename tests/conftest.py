import pytest

from terminal import posts


@pytest.fixture(autouse=True)
def no_post_lookups_over_the_network(monkeypatch):
    """A test that reaches X or Reddit fails loudly: it must pass its own `lookup` and `feed`."""
    async def x_post(url):
        raise AssertionError(f"test looked up {url} on X")

    async def get_feed(sub):
        raise AssertionError(f"test read r/{sub} from Reddit")

    monkeypatch.setattr(posts, "x_post", x_post)
    monkeypatch.setattr(posts, "_get_feed", get_feed)
    monkeypatch.setattr(posts, "_feeds", {})
    monkeypatch.setattr(posts, "_next_feed", 0.0)
