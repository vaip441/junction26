import json
from datetime import UTC, datetime

from terminal.contextdev import parse_scrape, parse_search


def test_parse_search_fixture():
    rows = parse_search(json.load(open("tests/fixtures/search_response.json")))
    assert len(rows) >= 5
    assert all(r["url"].startswith("http") and r["title"] and isinstance(r["description"], str) for r in rows)


def test_parse_search_drops_results_without_address_or_title():
    rows = parse_search({"results": [{"url": "https://a.example/x", "title": "T", "description": None},
                                     {"url": "", "title": "no address"}, {"url": "https://a.example/y"},
                                     {"url": "javascript:alert(1)", "title": "not a web address"}]})
    assert rows == [{"url": "https://a.example/x", "title": "T", "description": ""}]
    assert parse_search({"error": "nope"}) == []


def test_parse_scrape_returns_text_and_publish_time():
    text, ts = parse_scrape({"markdown": {"data": "# Story\nBody"}, "metadata": {"publishedTime": "2026-11-12T23:06:04+00:00"}})
    assert text == "# Story\nBody" and ts == datetime(2026, 11, 12, 23, 6, 4, tzinfo=UTC).timestamp()
    assert parse_scrape({"markdown": {"data": None}, "metadata": {"publishedTime": "not a date"}}) == ("", None)
    assert parse_scrape({}) == ("", None)


def test_limiter_allows_ten_a_minute_per_key():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    assert [lim.try_take(now=0) for _ in range(10)] == ["k1"] * 10
    assert lim.try_take(now=30) is None and lim.wait_time(now=30) == 30
    assert lim.try_take(now=60) == "k1"


def test_limiter_spreads_over_several_keys():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1", "k2"], per_minute=10)
    taken = [lim.try_take(now=0) for _ in range(21)]
    assert taken.count("k1") == 10 and taken.count("k2") == 10 and taken[-1] is None


def test_limiter_backs_off_a_key_the_server_refused():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    lim.refused("k1", retry_after=31, now=5)
    assert lim.try_take(now=35) is None and lim.try_take(now=36) == "k1"


def test_limiter_reserve_keeps_capacity_back_for_searches():
    from terminal.contextdev import Limiter

    lim = Limiter(["k1"], per_minute=10)
    assert [lim.try_take(now=0, reserve=5) for _ in range(6)] == ["k1"] * 5 + [None]
    assert [lim.try_take(now=0) for _ in range(6)] == ["k1"] * 5 + [None]
