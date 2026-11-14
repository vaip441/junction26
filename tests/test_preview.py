import asyncio

import pytest

from terminal import db as store
from terminal import preview


def test_image_prefers_the_secure_open_graph_image_and_resolves_it():
    page = """<html><head>
      <meta property="og:image" content="/small.png">
      <meta property="og:image:secure_url" content="https://cdn.example.com/big.jpg?a=1&amp;b=2">
      <meta name="twitter:image" content="https://cdn.example.com/twitter.jpg">
      <title>The page title</title></head></html>"""
    image, title = preview.image_from_html(page, "https://news.example.com/story")
    assert image == "https://cdn.example.com/big.jpg?a=1&b=2"
    assert title == "The page title"


def test_image_falls_back_to_twitter_and_a_relative_address():
    page = """<html><head><meta name="twitter:image" content="../card.png">
      <meta property="og:title" content="A cleaner title"></head></html>"""
    image, title = preview.image_from_html(page, "https://news.example.com/a/b")
    assert image == "https://news.example.com/card.png"
    assert title == "A cleaner title"


def test_image_from_a_link_and_no_image_at_all():
    page = '<html><head><link rel="image_src" href="https://img.example.com/a.png"></head></html>'
    assert preview.image_from_html(page, "https://example.com/") == ("https://img.example.com/a.png", None)
    assert preview.image_from_html("<html><head><title>No picture</title></head></html>", "https://example.com/") == (
        None, "No picture")


def test_a_data_url_is_not_a_preview():
    page = '<meta property="og:image" content="data:image/png;base64,AAAA">'
    assert preview.image_from_html(page, "https://example.com/") == (None, None)


def test_a_meta_tag_with_a_valueless_attribute_is_still_read():
    page = '<meta charset="utf-8"><meta property="og:image" content="https://img.example.com/a.png">'
    assert preview.image_from_html(page, "https://example.com/")[0] == "https://img.example.com/a.png"


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost/x", "http://169.254.169.254/latest",
                                 "http://[::1]/x", "file:///etc/passwd"])
def test_only_public_http_addresses_are_read(url):
    with pytest.raises(preview.PreviewError):
        asyncio.run(preview._check_public(url))
    asyncio.run(preview._check_public("https://8.8.8.8/"))  # a literal public address needs no network


def test_a_preview_is_read_once_and_remembered(tmp_path):
    db = store.connect(str(tmp_path / "t.db"))
    reads = []

    async def read(url):
        reads.append(url)
        return '<meta property="og:image" content="/a.png"><title>Story</title>', url

    async def run(now):
        return await preview.preview(db, "https://news.example.com/story", now=now, read=read)

    first = asyncio.run(run(1000.0))
    assert first == {"url": "https://news.example.com/story", "image": "https://news.example.com/a.png",
                     "title": "Story"}
    assert asyncio.run(run(1001.0))["image"] == "https://news.example.com/a.png"  # from the store
    assert len(reads) == 1


def test_a_page_without_an_image_is_retried_after_an_hour(tmp_path):
    db = store.connect(str(tmp_path / "t.db"))
    reads = []

    async def read(url):
        reads.append(url)
        return "<html><title>Still no picture</title></html>", url

    async def run(now):
        return await preview.preview(db, "https://news.example.com/story", now=now, read=read)

    assert asyncio.run(run(1000.0))["image"] is None
    asyncio.run(run(1000.0 + 3599))
    assert len(reads) == 1  # not asked again within the hour
    asyncio.run(run(1000.0 + 3601))
    assert len(reads) == 2


def test_a_page_that_cannot_be_read_is_no_preview_not_an_error(tmp_path):
    db = store.connect(str(tmp_path / "t.db"))

    async def read(url):
        raise TimeoutError("too slow")

    result = asyncio.run(preview.preview(db, "https://news.example.com/story", now=1000.0, read=read))
    assert result["image"] is None
