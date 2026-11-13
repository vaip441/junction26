"""Tests for trump_scraper.py.   Run:  python -m unittest -v test_trump_scraper

No network: Truth Social and FlareSolverr are simulated; test_data/statuses.json holds
real API objects captured from the live site.
"""
import contextlib
import csv
import io
import json
import os
import random
import socket
import sqlite3
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import trump_scraper as ts

FIXTURES = {s["id"]: s for s in json.loads((Path(__file__).parent / "test_data" / "statuses.json").read_text("utf-8"))}
T0 = 1_700_000_000  # an arbitrary "now" for simulated timelines


def iso(timestamp):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp)) + ".000Z"


def make_status(post_id, timestamp, text="hello", likes=0):
    return {
        "id": str(post_id),
        "created_at": iso(timestamp),
        "content": "<p>%s</p>" % text,
        "url": "https://truthsocial.com/@realDonaldTrump/%d" % post_id,
        "account": {"id": ts.ACCOUNT_ID, "acct": "realDonaldTrump", "statuses_count": 1},
        "reblog": None, "quote": None, "card": None, "media_attachments": [],
        "replies_count": 0, "reblogs_count": 0, "favourites_count": likes,
    }


class FakeApi:
    """A Truth Social timeline: posts keyed by id, served 20 at a time, newest first."""

    def __init__(self):
        self.posts = {}
        self.calls = 0
        self.fail_after = None  # raise on the Nth call from now

    def add(self, post_id, age_days=30.0, **kw):
        self.posts[post_id] = make_status(post_id, T0 - age_days * 86400, **kw)

    def fetch_page(self, max_id=None):
        self.calls += 1
        if self.fail_after is not None:
            self.fail_after -= 1
            if self.fail_after < 0:
                self.fail_after = None
                raise ts.ScrapeError("simulated network failure")
        ids = sorted((i for i in self.posts if max_id is None or i < max_id), reverse=True)
        return [json.loads(json.dumps(self.posts[i])) for i in ids[:ts.PAGE_LIMIT]]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "t.db"

    def tearDown(self):
        self._tmp.cleanup()

    def stored_ids(self):
        con = sqlite3.connect(str(self.db))
        try:
            return [row[0] for row in con.execute("SELECT id FROM posts ORDER BY id")]
        finally:
            con.close()

    def run_sync(self, api, **kw):
        """One sync against the simulated timeline; downloads the whole history unless told otherwise."""
        kw.setdefault("backfill", True)
        store = ts.Store(self.db)
        try:
            return ts.sync(store, api.fetch_page, now=T0, **kw)
        finally:
            store.close()


# ---------------------------------------------------------------- text ----

class TextTests(unittest.TestCase):
    def test_link_is_rebuilt_from_hidden_spans(self):
        text = ts.html_to_text(FIXTURES["117606259365899322"]["content"])
        self.assertEqual(
            text,
            "Lilly breaks ground in Pennsylvania's Lehigh Valley on a $3.5 billion site to make next-generation "
            "obesity medicines, the latest of 10 new U.S. sites since 2020: https://investor.lilly.com/news-releases/"
            "news-release-details/lilly-breaks-ground-pennsylvanias-lehigh-valley-35-billion-site")

    def test_paragraphs_do_not_glue_words_together(self):
        text = ts.html_to_text(FIXTURES["117592675594263904"]["content"])
        self.assertEqual(
            text,
            "Great job by Pete Hegseth — A MUST SEE! President DONALD J. TRUMP\n\n"
            "'A FARCE': Hegseth BLASTS impeachment effort, takes questions: https://www.youtube.com/watch?v=N48dH1heFEU")

    def test_line_breaks_and_nbsp_lines(self):
        text = ts.html_to_text(FIXTURES["117552846369178812"]["content"])
        lines = text.split("\n")
        self.assertEqual(lines[0], "TO THE GREAT PEOPLE OF ALABAMA, GET OUT AND VOTE FOR:")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "– Barry Moore for U.S. Senate")
        self.assertEqual(lines[3], "– Tommy Tuberville for Governor")
        self.assertNotIn(" ", text)
        self.assertNotIn("\n\n\n", text)

    def test_empty_and_media_only(self):
        self.assertEqual(ts.html_to_text("<p></p>"), "")
        self.assertEqual(ts.html_to_text(""), "")
        self.assertEqual(ts.html_to_text(None), "")

    def test_quote_stub_is_dropped_but_other_text_kept(self):
        stub = '<span class="quote-inline"><br/>RT: https://truthsocial.com/users/x/statuses/1</span>'
        self.assertEqual(ts.html_to_text("<p>%s</p>" % stub), "")
        self.assertEqual(ts.html_to_text("<p>Before %s</p><p>After</p>" % stub), "Before\n\nAfter")
        self.assertEqual(ts.html_to_text('<p>A<span class="quote-inline">x<span>y<br>z</span>w</span>B</p>'), "AB")

    def test_entities_and_whitespace(self):
        self.assertEqual(ts.html_to_text("<p>CNN &amp; MSDNC  are   &lt;bad&gt;</p>"), "CNN & MSDNC are <bad>")
        self.assertEqual(ts.html_to_text("<p>Get Ready!  Your favorite President</p>"), "Get Ready! Your favorite President")

    def test_clean_text_removes_invisible_characters_only(self):
        self.assertEqual(ts.clean_text("STATE ﻿TO GET​ BACK"), "STATE TO GET BACK")
        self.assertEqual(ts.clean_text("a‍b"), "a‍b")  # ZWJ is kept (emoji sequences)
        self.assertEqual(ts.clean_text("é"), "é")  # NFC
        self.assertEqual(ts.clean_text("bad \ud83d surrogate"), "bad � surrogate")
        ts.clean_text("bad \ud83d surrogate").encode("utf-8")  # must be encodable

    def test_extract_json_from_chrome_page(self):
        page = ('<html><head><meta name="color-scheme" content="light dark"></head><body><pre>'
                '[{"id":"1","content":"&lt;p&gt;A &amp;amp; B &lt;/pre&gt; \\u201cq\\u201d&lt;/p&gt;"}]'
                '</pre><div class="json-formatter-container"></div></body></html>')
        self.assertEqual(ts.extract_json(page), [{"id": "1", "content": "<p>A &amp; B </pre> “q”</p>"}])
        self.assertEqual(ts.extract_json("[]"), [])
        with self.assertRaises(ts.ScrapeError) as caught:
            ts.extract_json("<html><head><title>Just a moment...</title></head><body><h1>Checking</h1></body></html>")
        self.assertIn("Just a moment", str(caught.exception))

    def test_check_statuses(self):
        good = [make_status(5, T0)]
        self.assertIs(ts.check_statuses(good), good)
        with self.assertRaises(ts.ScrapeError):
            ts.check_statuses({"error": "Too many requests"})
        with self.assertRaises(ts.ScrapeError):
            ts.check_statuses("nope")
        wrong = make_status(5, T0)
        wrong["account"]["id"] = "999"
        with self.assertRaises(ts.ScrapeError):
            ts.check_statuses([wrong])
        with self.assertRaises(ts.ScrapeError):
            ts.check_statuses([{"id": "x"}])


class NormalizeTests(unittest.TestCase):
    def test_plain_post(self):
        row = ts.normalize_status(FIXTURES["107797156496908384"])
        self.assertEqual(row["id"], 107797156496908384)
        self.assertEqual(row["kind"], "post")
        self.assertEqual(row["text"], "Get Ready! Your favorite President will see you soon!")
        self.assertEqual(row["url"], "https://truthsocial.com/@realDonaldTrump/107797156496908384")
        self.assertEqual(row["created_at"], "2022-02-14T15:54:32.528Z")
        self.assertAlmostEqual(row["created_ts"], 1644854072.528, places=3)
        self.assertIsNone(row["author"])
        self.assertIsNone(row["quote_author"])
        self.assertGreater(row["likes"], 100000)

    def test_media_only_post(self):
        row = ts.normalize_status(FIXTURES["117609500488513990"])
        self.assertEqual(row["text"], "")
        media = json.loads(row["media"])
        self.assertEqual(len(media), 1)
        self.assertTrue(media[0].startswith("https://static-assets-1.truthsocial.com/"))

    def test_retruth_uses_the_original_post(self):
        status = FIXTURES["117552850047209387"]
        row = ts.normalize_status(status)
        self.assertEqual(row["kind"], "retruth")
        self.assertEqual(row["author"], "realDonaldTrump")
        self.assertTrue(row["text"].startswith("FAKE ALASKA CANDIDATE DANIAL J. SULLIVAN, JR., IS MISSING IN ACTION!"))
        self.assertNotIn("RT @", row["text"])
        self.assertEqual(row["id"], 117552850047209387)  # the retruth itself, not the original
        self.assertEqual(row["created_at"], status["created_at"])
        self.assertEqual(row["likes"], status["favourites_count"])  # the retruth's own counts

    def test_quote_post(self):
        row = ts.normalize_status(FIXTURES["117583463398468108"])
        self.assertEqual(row["kind"], "post")
        self.assertEqual(row["text"], "")  # only the inline "RT: link" stub, which is dropped
        self.assertEqual(row["quote_author"], "realDonaldTrump")
        self.assertEqual(row["quote_text"], "")
        self.assertGreaterEqual(len(json.loads(row["media"])), 1)  # own media + the quoted post's

    def test_link_card(self):
        row = ts.normalize_status(FIXTURES["117592675594263904"])
        self.assertEqual(row["link_title"], "'A FARCE': Hegseth BLASTS impeachment effort, takes questions")
        self.assertEqual(row["link_url"], "https://www.youtube.com/watch?v=N48dH1heFEU")

    def test_every_fixture_normalizes_and_round_trips_through_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ts.Store(Path(tmp) / "x.db")
            self.assertEqual(store.save_page(list(FIXTURES.values()), now=T0), len(FIXTURES))
            self.assertEqual(store.save_page(list(FIXTURES.values()), now=T0), 0)  # second time: nothing new
            posts = store.load_posts()
            self.assertEqual([p.id for p in posts], sorted((int(i) for i in FIXTURES), reverse=True))
            for post in posts:
                self.assertEqual(len(post.f_text), len(post.text))
            before = [(p.id, p.text, p.quote_text, p.link_title, p.media, p.likes) for p in posts]
            self.assertEqual(store.reparse(), len(FIXTURES))
            after = [(p.id, p.text, p.quote_text, p.link_title, p.media, p.likes) for p in store.load_posts()]
            self.assertEqual(before, after)
            store.close()


# -------------------------------------------------------------- search ----

def hit(query_text, text, **kw):
    return ts.Query.parse(query_text, **kw).matches((ts.fold(text),))


class SearchTests(unittest.TestCase):
    def test_whole_words_any_case(self):
        self.assertTrue(hit("tariff", "A big TARIFF on steel"))
        self.assertTrue(hit("TARIFF", "a tariff."))
        self.assertFalse(hit("tariff", "many tariffs"))
        self.assertFalse(hit("war", "toward a warning, an award"))
        self.assertTrue(hit("war", "the War!"))
        self.assertTrue(hit("biden", "Biden's plan"))
        self.assertTrue(hit("maga", "vote #MAGA now"))
        self.assertFalse(hit("trump", "RT @realDonaldTrump"))
        self.assertTrue(hit("@realdonaldtrump", "RT @realDonaldTrump: hi"))

    def test_wildcards(self):
        for word in ("tariff", "Tariffs", "TARIFFED"):
            self.assertTrue(hit("tariff*", "the %s are here" % word), word)
        self.assertFalse(hit("tariff*", "pretariff"))
        self.assertTrue(hit("*gate", "the Watergate hoax"))
        self.assertTrue(hit("zelensk*", "President Zelenskyy said"))
        self.assertTrue(hit("un*able", "simply unbelievable"))
        for bad in ("*", "-*", '"* *"'):
            with self.assertRaises(ts.QueryError):
                ts.Query.parse(bad)

    def test_phrases(self):
        self.assertTrue(hit('"fake news"', "The FAKE   NEWS media"))
        self.assertTrue(hit('"fake news"', "fake\nnews"))
        self.assertFalse(hit('"fake news"', "news that is fake"))
        self.assertFalse(hit('"fake news"', "fake newsroom"))
        self.assertTrue(hit('"witch hunt" russia', "RUSSIA, the greatest Witch Hunt"))

    def test_all_any_and_exclude(self):
        self.assertFalse(hit("china tariff", "China is great"))
        self.assertTrue(hit("china tariff", "China is great", match_any=True))
        self.assertTrue(hit("china -tariff", "China is great"))
        self.assertFalse(hit("china -tariff", "China tariff"))
        self.assertFalse(hit('china -"trade deal"', "China trade   deal"))
        self.assertTrue(hit("-biden", "nothing here"))
        self.assertTrue(hit("", "anything"))

    def test_quotes_dashes_accents_are_equivalent(self):
        self.assertTrue(hit("don't", "We don’t need it"))
        self.assertTrue(hit("don’t", "We don't need it"))
        self.assertTrue(hit("“fake news”", "Fake News!"))
        self.assertTrue(hit("sanchez", "Humberto Sánchez"))
        self.assertTrue(hit("so-called", "the so‑called experts"))
        self.assertTrue(hit("news", "\U0001d40d\U0001d404\U0001d416\U0001d412 alert"))  # bold maths letters
        self.assertTrue(hit('"united states"', "United States"))

    def test_numbers_and_symbols(self):
        self.assertTrue(hit("$100", "costs $100 today"))
        self.assertTrue(hit("$100", "costs $100."))
        self.assertFalse(hit("$100", "costs $100,000"))
        self.assertFalse(hit("$100", "costs $1000"))
        self.assertFalse(hit("100", "about 2,100 people"))
        self.assertTrue(hit("100%", "I am 100% in favor"))
        self.assertTrue(hit("u.s.", "the U.S. Senate"))
        self.assertTrue(hit("!!!", "FAKE NEWS!!!"))
        self.assertTrue(hit("2024", "#Trump2024 and 2024!"))

    def test_fold_keeps_length(self):
        sample = "Ångström “Q” ﬁ … İ ß \U0001f1fa\U0001f1f8 é ½ —  x"
        self.assertEqual(len(ts.fold(sample)), len(sample))

    def test_segments_rebuild_the_text_and_mark_matches(self):
        text = "Tariffs! The TARIFF on China’s steel — “Fake News” says no tariff."
        query = ts.Query.parse('tariff* "fake news" china')
        segments = query.segments(text, ts.fold(text))
        self.assertEqual("".join(chunk for chunk, _ in segments), text)
        self.assertEqual([chunk for chunk, marked in segments if marked], ["Tariffs", "TARIFF", "China", "Fake News", "tariff"])
        self.assertEqual(ts.Query.parse("").segments(text, ts.fold(text)), [(text, False)])
        self.assertEqual(ts.Query.parse("x").segments("", ""), [])

    def test_describe(self):
        self.assertEqual(ts.Query.parse('tariff* "fake news" -biden').describe(), 'tariff* AND "fake news" NOT biden')
        self.assertEqual(ts.Query.parse("a b", match_any=True).describe(), "a OR b")
        self.assertEqual(ts.Query.parse("").describe(), "(all posts)")
        self.assertEqual(ts.Query.parse('"unbalanced quote').describe(), "unbalanced AND quote")


def post(post_id, text, days_ago=1.0, kind="post", likes=0, quote="", link=""):
    return ts.Post(post_id, iso(T0 - days_ago * 86400), T0 - days_ago * 86400, "https://x/%d" % post_id, kind,
                   "someone" if kind == "retruth" else None, text, "q" if quote else None, quote or None,
                   link or None, "https://l" if link else None, "[]", 0, 0, likes)


class SearchPostsTests(unittest.TestCase):
    def setUp(self):
        self.posts = [  # newest first, as the store returns them
            post(9, "Tariffs on China", 1, likes=5),
            post(8, "China is fine", 2, likes=50),
            post(7, "A tariff!", 3, kind="retruth", likes=1),
            post(6, "", 4, quote="He said tariff too", likes=7),
            post(5, "Read this", 5, link="China tariff deal reached", likes=7),
            post(4, "Unrelated", 6),
        ]

    def ids(self, text, **kw):
        match_any = kw.pop("match_any", False)
        return [p.id for p in ts.search(self.posts, ts.Query.parse(text, match_any=match_any), **kw)]

    def test_matching_fields(self):
        self.assertEqual(self.ids("tariff"), [7, 6])  # body and quoted text; link titles only on request
        self.assertEqual(self.ids("tariff", links=True), [7, 6, 5])
        self.assertEqual(self.ids("tariff*"), [9, 7, 6])
        self.assertEqual(self.ids("china tariff*"), [9])
        self.assertEqual(self.ids("china tariff*", match_any=True), [9, 8, 7, 6])
        self.assertEqual(self.ids(""), [9, 8, 7, 6, 5, 4])

    def test_filters_and_sorting(self):
        self.assertEqual(self.ids("tariff*", kind="original"), [9, 6])
        self.assertEqual(self.ids("tariff*", kind="retruth"), [7])
        self.assertEqual(self.ids("tariff*", sort="oldest"), [6, 7, 9])
        self.assertEqual(self.ids("", sort="likes"), [8, 6, 5, 9, 7, 4])  # ties stay newest-first
        self.assertEqual(self.ids("", since=T0 - 3.5 * 86400), [9, 8, 7])
        self.assertEqual(self.ids("", until=T0 - 3.5 * 86400), [6, 5, 4])
        with self.assertRaises(ts.QueryError):
            self.ids("", sort="random")

    def test_variation_hints(self):
        hints = ts.variation_hints(self.posts, ts.Query.parse("tariff china*"))
        self.assertEqual(len(hints), 1)  # china* already has a wildcard
        self.assertEqual(hints[0]["term"], "tariff")
        self.assertEqual(hints[0]["wildcard"], "tariff*")
        self.assertEqual(hints[0]["words"], [("tariffs", 1)])
        self.assertEqual(ts.variation_hints(self.posts, ts.Query.parse("unrelated")), [])

    def test_day_ranges(self):
        since, until = ts.day_range("2025-01-20", "2025-01-20", utc=True)
        self.assertEqual(since, 1737331200.0)
        self.assertEqual(until - since, 86400.0)
        since, until = ts.day_range("2025-03-08", "2025-03-10")
        self.assertEqual(time.localtime(since)[:5], (2025, 3, 8, 0, 0))
        self.assertEqual(time.localtime(until)[:5], (2025, 3, 11, 0, 0))
        self.assertEqual(ts.day_range(None, None), (None, None))
        for bad in ("20/01/2025", "2025-13-01", "yesterday"):
            with self.assertRaises(ts.QueryError):
                ts.day_range(bad, None)
        with self.assertRaises(ts.QueryError):
            ts.day_range("2025-02-01", "2025-01-01")

    def test_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            tricky = [post(1, 'He said "hi",\nthen left \U0001f1fa\U0001f1f8', likes=3), post(2, "=1+1")]
            path = Path(tmp) / "out.csv"
            self.assertEqual(ts.export_posts(tricky, path, utc=True), 2)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(list(rows[0]), ts.EXPORT_FIELDS)
            self.assertEqual(rows[0]["text"], tricky[0].text)
            self.assertEqual(rows[1]["text"], "=1+1")
            self.assertEqual(rows[0]["id"], "1")
            self.assertTrue(rows[0]["created_at"].endswith("UTC"))
            path = Path(tmp) / "out.json"
            ts.export_posts(tricky, path)
            self.assertEqual(json.loads(path.read_text("utf-8"))[0]["text"], tricky[0].text)
            self.assertEqual(ts.export_posts([], Path(tmp) / "empty.csv"), 0)
            self.assertEqual((Path(tmp) / "empty.csv").read_text("utf-8-sig").strip(), ",".join(ts.EXPORT_FIELDS))
            with self.assertRaises(ts.QueryError):
                ts.export_posts(tricky, Path(tmp) / "out.txt")


# ---------------------------------------------------------------- sync ----

class SyncTests(TempDirCase):
    def fill(self, api, first, count, age_days=30.0):
        for post_id in range(first, first + count):
            api.add(post_id, age_days=age_days)

    def test_first_run_downloads_everything(self):
        api = FakeApi()
        self.fill(api, 1000, 95)
        summary = self.run_sync(api)
        self.assertEqual(self.stored_ids(), sorted(api.posts))
        self.assertEqual(summary["new"], 95)
        self.assertTrue(summary["history_complete"])
        self.assertFalse(summary["stopped"])
        self.assertEqual(api.calls, 5 + 2)  # 5 pages, then two empty answers before believing it is the end

    def test_nothing_new_is_cheap_and_adds_nothing(self):
        api = FakeApi()
        self.fill(api, 1000, 95)
        self.run_sync(api)
        api.calls = 0
        summary = self.run_sync(api)
        self.assertEqual(summary["new"], 0)
        self.assertEqual(api.calls, 1)  # one page: reaches known posts, all older than the refresh window

    def test_interrupted_backfill_resumes_without_gaps(self):
        api = FakeApi()
        self.fill(api, 1000, 205)
        summary = self.run_sync(api, max_pages=3)
        self.assertTrue(summary["stopped"])
        self.assertFalse(summary["history_complete"])
        self.assertEqual(len(self.stored_ids()), 60)
        summary = self.run_sync(api, max_pages=4)
        self.assertFalse(summary["history_complete"])
        summary = self.run_sync(api)
        self.assertTrue(summary["history_complete"])
        self.assertEqual(self.stored_ids(), sorted(api.posts))

    def test_new_posts_are_picked_up(self):
        api = FakeApi()
        self.fill(api, 1000, 50)
        self.run_sync(api)
        self.fill(api, 2000, 45)
        summary = self.run_sync(api)
        self.assertEqual(summary["new"], 45)
        self.assertEqual(self.stored_ids(), sorted(api.posts))

    def test_interrupted_head_leaves_no_hole(self):
        api = FakeApi()
        self.fill(api, 1000, 50)
        self.run_sync(api)
        self.fill(api, 2000, 90)  # 90 new posts = 5 pages before reaching known ones
        self.run_sync(api, max_pages=2)  # stops after the 40 newest: 50 new posts are still missing
        self.assertEqual(len(self.stored_ids()), 90)
        self.run_sync(api)
        self.assertEqual(self.stored_ids(), sorted(api.posts))

    def test_crash_in_the_middle_then_recover(self):
        api = FakeApi()
        self.fill(api, 1000, 130)
        api.fail_after = 3
        with self.assertRaises(ts.ScrapeError):
            self.run_sync(api)
        self.assertEqual(len(self.stored_ids()), 60)  # three pages were saved before the failure
        self.fill(api, 5000, 30)
        api.fail_after = 1
        with self.assertRaises(ts.ScrapeError):
            self.run_sync(api)
        self.run_sync(api)
        self.assertEqual(self.stored_ids(), sorted(api.posts))

    def test_recent_posts_get_their_counts_refreshed(self):
        api = FakeApi()
        self.fill(api, 1000, 30, age_days=30)
        self.fill(api, 2000, 30, age_days=1)  # posted yesterday
        self.run_sync(api)
        api.posts[2005]["favourites_count"] = 777  # recent: must be refreshed
        api.posts[1005]["favourites_count"] = 555  # a month old: left alone
        api.calls = 0
        self.run_sync(api)
        store = ts.Store(self.db)
        likes = {p.id: p.likes for p in store.load_posts()}
        store.close()
        self.assertEqual(likes[2005], 777)
        self.assertEqual(likes[1005], 0)
        self.assertEqual(api.calls, 2)  # the page of recent posts, plus one page reaching older ones

    def test_without_backfill_only_the_newest_page_is_read(self):
        api = FakeApi()
        self.fill(api, 1000, 100)
        summary = self.run_sync(api, backfill=False)  # empty database: the newest page starts it
        self.assertEqual(self.stored_ids(), list(range(1080, 1100)))
        self.assertEqual((api.calls, summary["new"], summary["stopped"], summary["history_complete"]), (1, 20, False, False))
        summary = self.run_sync(api, backfill=False)
        self.assertEqual((api.calls, summary["new"]), (2, 0))
        self.fill(api, 2000, 3)
        summary = self.run_sync(api, backfill=False)
        self.assertEqual(summary["new"], 3)
        self.assertEqual(self.stored_ids(), list(range(1080, 1100)) + [2000, 2001, 2002])
        summary = self.run_sync(api)  # history can still be added later
        self.assertTrue(summary["history_complete"])
        self.assertEqual(self.stored_ids(), sorted(api.posts))

    def test_sync_defaults_to_no_backfill(self):
        api = FakeApi()
        self.fill(api, 1000, 100)
        store = ts.Store(self.db)
        ts.sync(store, api.fetch_page, now=T0)
        store.close()
        self.assertEqual(len(self.stored_ids()), 20)

    def test_refresh_window_zero_reads_one_page(self):
        api = FakeApi()
        self.fill(api, 1000, 60, age_days=0.5)  # all recent: a normal update would re-read them all
        self.run_sync(api)
        api.calls = 0
        self.run_sync(api, backfill=False)
        self.assertEqual(api.calls, 3 + 1)  # three pages of recent posts, then the empty answer below them
        api.calls = 0
        api.add(2000, age_days=0)
        summary = self.run_sync(api, backfill=False, refresh_window=0)
        self.assertEqual((api.calls, summary["new"]), (1, 1))

    def test_full_resync_refreshes_old_posts(self):
        api = FakeApi()
        self.fill(api, 1000, 45)
        self.run_sync(api)
        api.posts[1001]["favourites_count"] = 42
        store = ts.Store(self.db)
        ts.reset_sync_state(store)
        store.close()
        summary = self.run_sync(api)
        self.assertEqual(summary["new"], 0)
        self.assertEqual(summary["seen"], 45)
        store = ts.Store(self.db)
        self.assertEqual({p.id: p.likes for p in store.load_posts()}[1001], 42)
        store.close()

    def test_deleted_newest_posts_do_not_confuse_it(self):
        api = FakeApi()
        self.fill(api, 1000, 45)
        self.run_sync(api)
        for post_id in (1044, 1043):
            del api.posts[post_id]
        self.fill(api, 2000, 3)
        self.run_sync(api)
        self.assertEqual(set(self.stored_ids()), set(api.posts) | {1044, 1043})  # deleted posts stay archived

    def test_bad_answers_raise(self):
        with self.assertRaises(ts.ScrapeError):
            self.run_sync(FakeApi())  # an account with no posts at all is not believable
        api = FakeApi()
        self.fill(api, 1000, 45)
        api.fetch_page = lambda max_id=None: [make_status(i, T0 - 9e6) for i in range(1044, 1024, -1)]  # ignores cursor
        with self.assertRaises(ts.ScrapeError):
            self.run_sync(api)

    def test_random_interruptions_never_lose_posts(self):
        rng = random.Random(20261114)
        for trial in range(25):
            db = self.dir / ("r%d.db" % trial)
            api, next_id = FakeApi(), 1000
            for _ in range(rng.randint(3, 8)):
                for _ in range(rng.randint(0, 70)):
                    api.add(next_id, age_days=rng.choice([0.5, 2, 10, 60]))
                    next_id += rng.randint(1, 3)
                if not api.posts:
                    continue
                store = ts.Store(db)
                try:
                    if rng.random() < 0.4:
                        api.fail_after = rng.randint(0, 6)
                    ts.sync(store, api.fetch_page, now=T0, max_pages=rng.choice([None, 1, 2, 5]),
                            backfill=rng.random() < 0.8)
                except ts.ScrapeError:
                    pass
                finally:
                    api.fail_after = None
                    store.close()
            if not api.posts:
                continue
            store = ts.Store(db)
            summary = ts.sync(store, api.fetch_page, now=T0, backfill=True)
            stored = {p.id for p in store.load_posts()}
            store.close()
            self.assertTrue(summary["history_complete"], trial)
            self.assertEqual(stored, set(api.posts), trial)


class ClientTests(unittest.TestCase):
    class Solver:
        def __init__(self, answers):
            self.answers, self.urls, self.reopened = list(answers), [], 0

        def get(self, url):
            self.urls.append(url)
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return {"response": "<html><body><pre>%s</pre></body></html>" % json.dumps(answer)}

        def close_session(self):
            pass

        def open_session(self):
            self.reopened += 1

    def client(self, answers, interval=3.0):
        self.now, self.sleeps = 0.0, []

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        solver = self.Solver(answers)
        return ts.TruthSocial(solver, interval=interval, sleep=sleep, clock=lambda: self.now), solver

    def test_requests_are_spaced(self):
        page = [make_status(5, T0)]
        client, solver = self.client([page, page, page])
        client.fetch_page()
        self.now += 1.0  # one second of other work
        client.fetch_page(max_id=5)
        client.fetch_page(max_id=4)
        self.assertEqual(self.sleeps, [2.0, 3.0])
        self.assertTrue(solver.urls[0].endswith("/statuses?limit=20"))
        self.assertTrue(solver.urls[1].endswith("/statuses?limit=20&max_id=5"))

    def test_rate_limit_backs_off_and_slows_down(self):
        blocked = ts.ScrapeError("FlareSolverr: Error: Error solving the challenge. Cloudflare has blocked this request.")
        page = [make_status(5, T0)]
        client, solver = self.client([blocked, {"error": "Too many requests"}, page], interval=8.0)
        self.assertEqual(len(client.fetch_page()), 1)
        self.assertEqual(client.interval, 18.0)  # widened by half, twice
        self.assertGreaterEqual(sum(self.sleeps), 90 + 300)
        self.assertEqual(solver.reopened, 2)

    def test_gives_up_eventually(self):
        client, _ = self.client([ts.ScrapeError("boom")] * 4)
        with self.assertRaises(ts.ScrapeError) as caught:
            client.fetch_page()
        self.assertIn("4 attempts", str(caught.exception))
        client, _ = self.client([ts.ScrapeError("Cloudflare has blocked this request")] * 5)
        with self.assertRaises(ts.ScrapeError):
            client.fetch_page()


class StoreTests(TempDirCase):
    def test_snapshot_is_a_slim_faithful_copy(self):
        api = FakeApi()
        for post_id in range(1000, 1045):
            api.add(post_id, text="post <b>%d</b> &amp; more" % post_id)
        self.run_sync(api)
        out = self.dir / "snap.db"
        self.assertEqual(ts.write_snapshot(self.db, out), 45)
        original, copy = ts.Store(self.db), ts.Store(out)
        self.assertEqual([(p.id, p.text, p.created_at) for p in original.load_posts()],
                         [(p.id, p.text, p.created_at) for p in copy.load_posts()])
        self.assertEqual(original.stats(), copy.stats())
        self.assertEqual(copy.db.execute("SELECT COUNT(*) FROM posts WHERE raw IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(original.db.execute("SELECT COUNT(*) FROM posts WHERE raw IS NULL").fetchone()[0], 0)
        original.close()
        copy.close()
        self.assertEqual(ts.write_snapshot(self.db, out), 45)  # overwriting an existing snapshot works
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_only_one_update_at_a_time(self):
        with ts.UpdateLock(self.db):
            with self.assertRaises(ts.UpdateBusy):
                with ts.UpdateLock(self.db):
                    pass
        with ts.UpdateLock(self.db):  # released again
            pass

    def test_stats(self):
        store = ts.Store(self.db)
        self.assertEqual(store.stats()["posts"], 0)
        store.close()
        api = FakeApi()
        api.add(1, age_days=3)
        api.add(2, age_days=1)
        self.run_sync(api)
        store = ts.Store(self.db)
        stats = store.stats()
        store.close()
        self.assertEqual((stats["posts"], stats["retruths"], stats["history_complete"]), (2, 0, True))
        self.assertEqual(stats["newest"], T0 - 86400)
        self.assertEqual(stats["account_posts"], 1)
        self.assertIsNotNone(stats["last_sync"])


class RemoteTests(unittest.TestCase):
    def test_remote_command_is_quoted(self):
        remote = {"ssh": "box", "dir": "/data/my scraper", "python": "/usr/bin/python3", "wrap": "nice -n 10"}
        self.assertEqual(
            ts._remote_command(remote, "update", "--delay", 3.0, "--max-pages", 5),
            "cd '/data/my scraper' && nice -n 10 /usr/bin/python3 -u trump_scraper.py update --delay 3.0 --max-pages 5")


class WebTests(TempDirCase):
    def test_search_api_over_http(self):
        store = ts.Store(self.db)
        store.save_page(list(FIXTURES.values()), now=T0)
        store.close()
        app = ts.App(self.db)
        handler = type("H", (ts.Handler,), {"app": app})
        server = ts.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(base + path, timeout=10) as response:
                return response.status, response.headers.get("Content-Type"), response.read()

        try:
            status, kind, body = get("/")
            self.assertEqual(status, 200)
            self.assertTrue(kind.startswith("text/html"))
            self.assertIn(b"<title>Trump Truth Social search</title>", body)

            data = json.loads(get("/api/search?q=hegseth")[2])
            self.assertEqual(data["total"], 1)
            result = data["results"][0]
            self.assertEqual(result["id"], "117592675594263904")
            self.assertEqual("".join(chunk for chunk, _ in result["text"]),
                             ts.html_to_text(FIXTURES["117592675594263904"]["content"]))
            self.assertEqual([chunk for chunk, marked in result["text"] if marked], ["Hegseth", "Hegseth"])
            self.assertEqual(data["description"], "hegseth")

            everything = json.loads(get("/api/search?q=")[2])
            self.assertEqual(everything["total"], len(FIXTURES))
            self.assertEqual([r["id"] for r in everything["results"]], sorted(FIXTURES, key=int, reverse=True))
            retruths = json.loads(get("/api/search?q=&type=retruth")[2])
            self.assertEqual([(r["kind"], r["author"]) for r in retruths["results"]], [("retruth", "realDonaldTrump")])
            paged = json.loads(get("/api/search?q=&offset=2&limit=2")[2])
            self.assertEqual([r["id"] for r in paged["results"]], [r["id"] for r in everything["results"][2:4]])
            self.assertEqual(json.loads(get("/api/search?q=farce")[2])["total"], 1)
            self.assertEqual(json.loads(get("/api/search?q=blasts&links=1")[2])["total"], 1)
            self.assertEqual(json.loads(get("/api/search?q=%2A")[2]).get("error") is not None, True)
            self.assertIn("error", json.loads(get("/api/search?q=x&since=nonsense")[2]))
            self.assertIn("error", json.loads(get("/api/search?q=x&sort=bogus")[2]))

            status_data = json.loads(get("/api/status")[2])
            self.assertEqual(status_data["posts"], len(FIXTURES))
            self.assertEqual(status_data["sync"], {"live": False, "checked": None, "error": None})
        finally:
            server.shutdown()
            server.server_close()


# --------------------------------------------------------------- watch ----

class FakeSolver:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class WatchTests(TempDirCase):
    """ts.watch() against a simulated timeline, clock and browser."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(ts, "load_remote", return_value=None)  # never read the real config.json
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = FakeApi()
        self.now = 1000.0
        self.reported, self.sources, self.polls, self.poll_times, self.logs, self.solvers = [], [], [], [], [], []

    def seed(self, count=30):
        """A database that already holds the newest page of a timeline of `count` posts."""
        for post_id in range(1000, 1000 + count):
            self.api.add(post_id)
        self.run_sync(self.api, backfill=False)
        self.api.calls = 0

    def connect(self, url, interval, log, sleep):
        solver = FakeSolver()
        self.solvers.append(solver)
        return solver, types.SimpleNamespace(fetch_page=self.api.fetch_page, interval=interval)

    def tick(self, seconds):
        self.assertGreater(seconds, 0)
        self.now += seconds

    def watch(self, steps=(), **kw):
        """Run a watch for len(steps) + 1 polls; after each poll but the last, the next step (or None) runs."""
        steps = list(steps)
        done = []

        def on_poll(error):
            self.polls.append(error)
            self.poll_times.append(self.now)
            if not steps:
                done.append(True)
                return
            step = steps.pop(0)
            if step:
                step()

        kw.setdefault("connect", self.connect)
        def on_new(posts, live, source):
            self.reported.append(([p.id for p in posts], live))
            self.sources.append(source)

        ts.watch(self.db, on_new=on_new, on_poll=on_poll, log=self.logs.append, should_stop=lambda: bool(done),
                 clock=lambda: self.now, sleep=self.tick, **kw)

    def add(self, *post_ids):
        return lambda: [self.api.add(post_id, age_days=0) for post_id in post_ids]

    def gaps(self):
        return [round(b - a, 6) for a, b in zip(self.poll_times, self.poll_times[1:])]

    def test_each_new_post_is_reported_once_oldest_first(self):
        self.seed()
        self.watch([self.add(2001, 2000), None, self.add(2002)])
        self.assertEqual(self.reported, [([2000, 2001], True), ([2002], True)])
        self.assertEqual(self.polls, [None] * 4)
        self.assertEqual(self.api.calls, 4)  # one request per poll
        self.assertEqual(len(self.solvers), 1)  # one browser for the whole watch ...
        self.assertEqual(self.solvers[0].closed, 1)  # ... shut down at the end
        self.assertEqual(self.stored_ids(), list(range(1010, 1030)) + [2000, 2001, 2002])

    def test_polls_are_evenly_spaced(self):
        self.seed()
        self.watch([None, None, None])
        self.assertEqual(self.gaps(), [ts.WATCH_INTERVAL] * 3)
        self.poll_times.clear()
        self.watch([None, None], interval=1)  # too fast for the rate limit: raised to the minimum
        self.assertEqual(self.gaps(), [ts.MIN_WATCH_INTERVAL] * 2)

    def test_posts_made_while_nobody_watched_are_reported_as_not_live(self):
        self.seed()
        for post_id in range(2000, 2045):
            self.api.add(post_id, age_days=0.1)
        self.watch()
        self.assertEqual(self.reported, [(list(range(2000, 2045)), False)])
        self.assertEqual(self.api.calls, 3)  # 45 new posts: three pages until the stored ones are reached

    def test_an_empty_database_starts_from_now(self):
        for post_id in range(1000, 1030):
            self.api.add(post_id)
        self.watch([self.add(5000)])
        self.assertEqual(self.reported, [([5000], True)])  # the 20 posts that were already there are not news
        self.assertEqual(self.stored_ids(), list(range(1010, 1030)) + [5000])
        self.assertTrue(any("Watching from here on" in line for line in self.logs))

    def test_a_failed_poll_is_retried_and_loses_nothing(self):
        self.seed()

        def trouble():
            for post_id in range(2000, 2045):
                self.api.add(post_id, age_days=0)
            self.api.fail_after = 1  # the next poll reads one page, then the connection breaks

        self.watch([trouble, None, self.add(3000)])
        self.assertEqual(self.polls, [None, "simulated network failure", None, None])
        # nothing was reported from the broken poll; the next one reports everything, in order, as not live
        self.assertEqual(self.reported, [(list(range(2000, 2045)), False), ([3000], True)])
        self.assertEqual(len(self.solvers), 2)  # the browser was restarted after the failure
        self.assertEqual([solver.closed for solver in self.solvers], [1, 1])
        self.assertEqual(self.gaps(), [ts.WATCH_INTERVAL, 2 * ts.WATCH_INTERVAL, ts.WATCH_INTERVAL])  # backed off once
        self.assertTrue(any("Could not check for new posts (simulated network failure)" in line for line in self.logs))

    def test_a_failing_report_is_retried(self):
        self.seed()
        calls, polls = [], []

        def on_new(posts, live, source):
            calls.append(([p.id for p in posts], live))
            if len(calls) == 1:
                raise OSError("disk full")

        self.api.add(2000, age_days=0)
        ts.watch(self.db, on_new=on_new, on_poll=polls.append, log=self.logs.append, retry_first=True,
                 should_stop=lambda: len(polls) == 2, connect=self.connect, clock=lambda: self.now, sleep=self.tick)
        self.assertEqual(polls, ["OSError: disk full", None])
        self.assertEqual(calls, [([2000], False), ([2000], False)])

    def test_first_poll_failure_is_raised_unless_asked_to_retry(self):
        self.seed()
        self.api.fail_after = 0
        with self.assertRaises(ts.ScrapeError):
            self.watch()
        self.assertEqual([solver.closed for solver in self.solvers], [1])
        self.api.fail_after = 0
        self.polls.clear()
        self.watch([self.add(2000)], retry_first=True)
        self.assertEqual(self.polls, ["simulated network failure", None])
        self.assertEqual(self.reported, [([2000], False)])

    def test_setup_problem_is_raised_with_its_message(self):
        self.seed()

        def no_flaresolverr(url, interval, log, sleep):
            raise ts.ScrapeError("FlareSolverr is not answering")

        with self.assertRaises(ts.ScrapeError) as caught:
            self.watch(connect=no_flaresolverr)
        self.assertIn("FlareSolverr is not answering", str(caught.exception))
        with ts.UpdateLock(self.db):  # the lock was released on the way out
            pass

    def test_follows_another_updater_then_takes_over(self):
        self.seed()
        other = ts.UpdateLock(self.db)
        other.__enter__()  # another process is updating this database

        def other_stores_a_post():
            self.api.add(2000, age_days=0)
            self.run_sync(self.api, backfill=False, refresh_window=0)
            self.api.calls = 0

        def other_finishes():
            other.__exit__()
            self.api.add(2001, age_days=0)

        self.watch([other_stores_a_post, other_finishes, None])
        self.assertEqual(self.reported, [([2000], True), ([2001], True)])
        self.assertEqual(len(self.solvers), 1)  # only connected once it had the lock
        self.assertEqual(self.api.calls, 2)  # polls three and four scraped
        self.assertEqual(sum("following what it stores" in line for line in self.logs), 1)
        self.assertEqual(sum("scraping here from now on" in line for line in self.logs), 1)
        with ts.UpdateLock(self.db):  # the watch released the lock when it ended
            pass

    def test_holds_the_update_lock_while_scraping(self):
        self.seed()

        def check():
            with self.assertRaises(ts.UpdateBusy):
                with ts.UpdateLock(self.db):
                    pass

        self.watch([check])

    def test_browser_is_restarted_when_its_session_gets_old(self):
        self.seed()
        with mock.patch.object(ts, "SESSION_LIFETIME", 50.0):
            self.watch([None] * 3)  # polls at 0, 20, 40 and 60 seconds
        self.assertEqual(len(self.solvers), 2)
        self.assertEqual([solver.closed for solver in self.solvers], [1, 1])

    def test_remote_machine_mode_downloads_instead_of_scraping(self):
        self.seed()
        ts.load_remote.return_value = {"ssh": "box", "dir": "/srv/scraper", "python": "python3", "wrap": ""}
        asked = []

        def fake_run_update(db_path, solver_url=None, **kw):  # stands in for "ssh update + download"
            asked.append(kw)
            self.run_sync(self.api, backfill=False, refresh_window=0)

        def never(*args):
            raise AssertionError("must not start a browser here")

        with mock.patch.object(ts, "run_update", fake_run_update):
            self.watch([self.add(2000), None], connect=never)
        self.assertEqual(self.reported, [([2000], True)])
        self.assertEqual(len(asked), 3)
        self.assertTrue(all(kw["quick"] and kw["quiet"] for kw in asked))
        self.assertEqual(self.gaps(), [ts.REMOTE_WATCH_INTERVAL] * 2)

    def test_stops_promptly_when_asked(self):
        self.seed()
        stop, naps = [], []

        def sleep(seconds):
            naps.append(seconds)
            self.now += seconds
            if len(naps) == 3:
                stop.append(True)

        ts.watch(self.db, log=self.logs.append, should_stop=lambda: bool(stop), connect=self.connect,
                 clock=lambda: self.now, sleep=sleep)
        self.assertEqual(naps, [0.5, 0.5, 0.5])  # woke every half second and left right after the stop
        self.assertEqual(self.solvers[0].closed, 1)


class WatchCommandTests(TempDirCase):
    def setUp(self):
        super().setUp()
        for name in ("load_remote", "load_token"):  # never read the real config.json or environment
            patcher = mock.patch.object(ts, name, return_value=None)
            patcher.start()
            self.addCleanup(patcher.stop)
        store = ts.Store(self.db)
        store.save_page(list(FIXTURES.values()), now=T0)
        self.posts = store.load_posts()[::-1]  # oldest first, as a watch reports them
        store.close()

    def run_command(self, *argv, live=True):
        def fake_watch(db_path, solver_url=None, *, interval=None, on_new=None, log=print, **kw):
            self.interval = interval
            log("connected")
            on_new(self.posts, live, "poll")

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ts, "watch", fake_watch), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ts.main(["watch", "--db", str(self.db)] + list(argv))
        self.assertEqual(code, 0)
        return out.getvalue(), err.getvalue()

    def test_json_lines_on_stdout_and_in_the_feed_file(self):
        feed = self.dir / "sub" / "feed.jsonl"
        out, err = self.run_command("--json", "--jsonl", str(feed))
        records = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([r["id"] for r in records], sorted(FIXTURES, key=int))
        self.assertEqual([json.loads(line) for line in feed.read_text("utf-8").splitlines()], records)
        self.assertIn("connected", err)  # messages stay out of the data stream
        self.assertIn("Watching @realDonaldTrump", err)
        record = {r["id"]: r for r in records}["117592675594263904"]
        self.assertEqual(record["text"], ts.html_to_text(FIXTURES["117592675594263904"]["content"]))
        self.assertEqual(record["created_at"], FIXTURES["117592675594263904"]["created_at"])
        self.assertEqual(record["url"], "https://truthsocial.com/@realDonaldTrump/117592675594263904")
        self.assertIs(record["live"], True)
        self.assertEqual((record["type"], record["retruth_of"]), ("post", None))
        self.assertRegex(record["detected_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertGreater(record["delay_seconds"], 0)
        self.assertEqual(sorted(record), sorted(
            "id created_at detected_at delay_seconds live source type retruth_of text quote_of quote_text "
            "link_title link_url media url".split()))
        self.assertEqual([r["retruth_of"] for r in records if r["type"] == "retruth"], ["realDonaldTrump"])
        self.assertTrue(all(isinstance(r["media"], list) for r in records))
        self.run_command("--json", "--jsonl", str(feed))  # the feed file is appended to, never rewritten
        self.assertEqual(len(feed.read_text("utf-8").splitlines()), 2 * len(records))

    def test_keywords_choose_what_is_reported(self):
        out, _ = self.run_command("hegseth", "--json")
        self.assertEqual([json.loads(line)["id"] for line in out.splitlines()], ["117592675594263904"])
        out, _ = self.run_command("--json", "--type", "retruth", live=False)
        records = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(r["type"], r["live"]) for r in records], [("retruth", False)])
        out, _ = self.run_command("--json", "--exclude", "hegseth")
        self.assertEqual(len(out.splitlines()), len(FIXTURES) - 1)
        out, _ = self.run_command("nosuchword", "--json", "--jsonl", str(self.dir / "none.jsonl"))
        self.assertEqual(out, "")
        self.assertFalse((self.dir / "none.jsonl").exists())

    def test_readable_output(self):
        out, err = self.run_command("hegseth", "--no-color", "--utc", "--interval", "30")
        self.assertEqual(err, "")
        self.assertEqual(self.interval, 30.0)
        self.assertIn("checking every 30 s, reporting posts matching hegseth", out)
        self.assertIn("--- new post, posted ", out)  # the fixture is old: reported with its age
        self.assertIn("https://truthsocial.com/@realDonaldTrump/117592675594263904", out)
        self.assertIn("Hegseth", out)
        self.assertEqual(out.count("--- new post"), 1)

    def test_parser_defaults(self):
        parser = ts.build_parser()
        args = parser.parse_args(["watch"])
        self.assertEqual((args.terms, args.interval, args.jsonl, args.json, args.type), ([], None, None, False, "all"))
        args = parser.parse_args(["update"])
        self.assertEqual((args.history, args.full, args.quick, args.max_pages), (False, False, False, None))
        self.assertTrue(parser.parse_args(["update", "--history"]).history)
        args = parser.parse_args(["search", "a", "--any", "--exclude", "b", "--links", "--utc", "--type", "original"])
        self.assertEqual((args.any, args.exclude, args.links, args.utc, args.type), (True, ["b"], True, True, "original"))
        self.assertEqual(ts.watch_interval(), ts.WATCH_INTERVAL)
        self.assertEqual(ts.watch_interval(3), ts.MIN_WATCH_INTERVAL)
        ts.load_remote.return_value = {"ssh": "box", "dir": "/x", "python": "python3", "wrap": ""}
        self.assertEqual(ts.watch_interval(), ts.REMOTE_WATCH_INTERVAL)


class UpdateTests(TempDirCase):
    REMOTE = {"ssh": "box", "dir": "/srv/scraper", "python": "python3", "wrap": ""}

    def remote_update(self, exit_code, **kw):
        """run_update() with a remote machine configured; returns (ssh command, downloads, messages)."""
        commands, pulls, messages = [], [], []

        def fake_ssh(remote, command, log, should_stop=None):
            commands.append(command)
            log("Scraping ...")
            log("Error: something broke" if exit_code == 1 else "Done.")
            return exit_code

        with mock.patch.object(ts, "load_remote", return_value=dict(self.REMOTE)), \
                mock.patch.object(ts, "_ssh", fake_ssh), \
                mock.patch.object(ts, "pull_database", lambda remote, db_path, log=print: pulls.append(db_path)):
            result = ts.run_update(self.db, log=messages.append, **kw)
        self.assertIsNone(result)
        return commands[0], pulls, messages

    def test_remote_update_passes_the_options_on(self):
        command, pulls, messages = self.remote_update(0)
        self.assertEqual(command, "cd /srv/scraper && python3 -u trump_scraper.py update --delay 8.0")
        self.assertEqual(pulls, [self.db])
        self.assertEqual(messages, ["[box] Scraping ...", "[box] Done."])
        self.assertTrue(self.remote_update(0, quick=True)[0].endswith("update --delay 8.0 --quick"))
        self.assertTrue(self.remote_update(0, backfill=True, max_pages=2)[0].endswith("--delay 8.0 --history --max-pages 2"))
        self.assertTrue(self.remote_update(0, full=True)[0].endswith("--delay 8.0 --history --full"))

    def test_remote_busy_still_downloads_and_quiet_says_nothing(self):
        command, pulls, messages = self.remote_update(ts.EXIT_BUSY)
        self.assertEqual(pulls, [self.db])
        self.assertTrue(any("already updating" in line for line in messages))
        command, pulls, messages = self.remote_update(ts.EXIT_BUSY, quiet=True)
        self.assertEqual((pulls, messages), ([self.db], []))

    def test_remote_failure_carries_the_remote_message(self):
        with self.assertRaises(ts.ScrapeError) as caught:
            self.remote_update(1, quiet=True)
        self.assertIn("exit code 1", str(caught.exception))
        self.assertIn("Error: something broke", str(caught.exception))

    def test_browser_server_is_shut_down_when_connecting_fails(self):
        events = []

        class Broken(ts.FlareSolverr):
            def start(self):
                events.append("start")

            def open_session(self):
                raise ts.ScrapeError("no browser")

            def close(self):
                events.append("close")

        with self.assertRaises(ts.ScrapeError):
            with Broken("http://127.0.0.1:1"):
                self.fail("must not get here")
        self.assertEqual(events, ["start", "close"])

    def test_ui_follows_the_watch(self):
        store = ts.Store(self.db)
        store.save_page(list(FIXTURES.values())[:3], now=T0)
        store.close()
        release = threading.Event()

        def fake_watch(db_path, solver_url=None, *, on_poll=None, should_stop=None, retry_first=False, **kw):
            self.assertTrue(retry_first)  # the page must keep trying, not die on a bad start
            store = ts.Store(db_path)
            store.save_page(list(FIXTURES.values()), now=T0)  # a poll brings in more posts
            store.close()
            on_poll(None)
            release.wait(10)
            on_poll("boom")

        app = ts.App(self.db)
        self.assertEqual(app.status()["posts"], 3)
        with mock.patch.object(ts, "watch", fake_watch), mock.patch.object(ts, "load_token", return_value=None):
            self.assertTrue(app.start_watch())
            self.assertFalse(app.start_watch())  # already running
            deadline = time.time() + 10
            while app.status()["sync"]["checked"] is None and time.time() < deadline:
                time.sleep(0.01)
            status = app.status()
            self.assertEqual(status["posts"], len(FIXTURES))  # the page sees the new posts without a restart
            self.assertTrue(status["sync"]["live"])
            self.assertIsNone(status["sync"]["error"])
            release.set()
            while app.status()["sync"]["live"] and time.time() < deadline:
                time.sleep(0.01)
        status = app.status()
        self.assertEqual((status["sync"]["live"], status["sync"]["error"]), (False, "boom"))


# ---------------------------------------------------------- websockets ----

def wait_until(condition, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return bool(condition())


class WebSocketTests(unittest.TestCase):
    """The frame code against the byte-for-byte examples of RFC 6455."""

    def pair(self, client=True):
        ours, theirs = socket.socketpair()
        self.addCleanup(ours.close)
        self.addCleanup(theirs.close)
        theirs.settimeout(5)
        return ts.WebSocket(ours, client=client), theirs

    def test_handshake_key_matches_the_rfc_example(self):
        self.assertEqual(ts._ws_accept("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_frames_match_the_rfc_examples(self):
        self.assertEqual(ts._ws_frame(0x1, b"Hello"), bytes.fromhex("810548656c6c6f"))
        self.assertEqual(ts._ws_mask(bytes.fromhex("7f9f4d5158"), bytes.fromhex("37fa213d")), b"Hello")
        self.assertEqual(ts._ws_frame(0x9, b"Hello"), bytes.fromhex("890548656c6c6f"))
        masked = ts._ws_frame(0x1, b"Hello", mask=True)
        self.assertEqual((masked[0], masked[1], len(masked)), (0x81, 0x85, 11))
        self.assertEqual(ts._ws_mask(masked[6:], masked[2:6]), b"Hello")
        self.assertEqual(ts._ws_frame(0x2, b"x" * 125)[:2], bytes.fromhex("827d"))
        self.assertEqual(ts._ws_frame(0x2, b"x" * 256)[:4], bytes.fromhex("827e0100"))
        self.assertEqual(ts._ws_frame(0x2, b"x" * 65535)[:4], bytes.fromhex("827effff"))
        self.assertEqual(ts._ws_frame(0x2, b"x" * 65536)[:10], bytes.fromhex("827f0000000000010000"))
        for size in (0, 1, 3, 4, 5, 1000):
            data = os.urandom(size)
            self.assertEqual(ts._ws_mask(ts._ws_mask(data, b"\x01\x02\x03\x04"), b"\x01\x02\x03\x04"), data)

    def test_receiving_messages(self):
        connection, peer = self.pair()
        peer.sendall(bytes.fromhex("810548656c6c6f"))  # one unmasked text frame
        self.assertEqual(connection.recv(timeout=5), "Hello")
        peer.sendall(bytes.fromhex("010348656c"))  # a fragmented message ...
        peer.sendall(bytes.fromhex("890548656c6c6f"))  # ... with a ping in the middle ...
        peer.sendall(bytes.fromhex("80026c6f"))  # ... and its last fragment
        self.assertEqual(connection.recv(timeout=5), "Hello")
        pong = peer.recv(100)  # the ping was answered with a masked pong carrying the same bytes
        self.assertEqual((pong[0], pong[1], len(pong)), (0x8A, 0x85, 11))
        self.assertEqual(ts._ws_mask(pong[6:], pong[2:6]), b"Hello")
        peer.sendall(bytes.fromhex("827e0100") + bytes(range(256)))  # 16-bit length
        self.assertEqual(connection.recv(timeout=5), bytes(range(256)))
        big = os.urandom(65536)
        threading.Thread(target=peer.sendall, args=(bytes.fromhex("827f0000000000010000") + big,)).start()  # 64-bit length
        self.assertEqual(connection.recv(timeout=5), big)
        text = "“Tariffs” ✓ " * 3
        peer.sendall(ts._ws_frame(0x1, text.encode("utf-8")))
        self.assertEqual(connection.recv(timeout=5), text)

    def test_a_timeout_keeps_what_has_arrived(self):
        connection, peer = self.pair()
        self.assertIsNone(connection.recv(timeout=0.05))
        peer.sendall(bytes.fromhex("810548656c"))  # most of a frame
        self.assertIsNone(connection.recv(timeout=0.05))
        peer.sendall(bytes.fromhex("6c6f") + bytes.fromhex("8a00") + bytes.fromhex("81026f6b"))  # the rest, a pong, "ok"
        self.assertEqual(connection.recv(timeout=5), "Hello")
        self.assertEqual(connection.recv(timeout=5), "ok")

    def test_close_and_protocol_errors(self):
        connection, peer = self.pair()
        peer.sendall(bytes.fromhex("880203e8"))  # close, code 1000
        with self.assertRaises(ts.WebSocketError) as caught:
            connection.recv(timeout=5)
        self.assertIn("code 1000", str(caught.exception))
        echo = peer.recv(100)
        self.assertEqual((echo[0], echo[1]), (0x88, 0x82))  # the close was acknowledged
        connection, peer = self.pair()
        peer.close()
        with self.assertRaises(ts.WebSocketError):
            connection.recv(timeout=5)
        connection, peer = self.pair()
        peer.sendall(bytes.fromhex("818537fa213d7f9f4d5158"))  # a masked frame, which a server must never send
        with self.assertRaises(ts.WebSocketError):
            connection.recv(timeout=5)
        connection, peer = self.pair()
        peer.sendall(bytes.fromhex("c10548656c6c6f"))  # compressed, which was never agreed
        with self.assertRaises(ts.WebSocketError):
            connection.recv(timeout=5)

    def test_the_server_end_reads_masked_frames_and_sends_plain_ones(self):
        connection, peer = self.pair(client=False)
        peer.sendall(bytes.fromhex("818537fa213d7f9f4d5158"))  # the RFC's masked "Hello"
        self.assertEqual(connection.recv(timeout=5), "Hello")
        connection.send("Hello")
        self.assertEqual(peer.recv(100), bytes.fromhex("810548656c6c6f"))
        peer.sendall(bytes.fromhex("810548656c6c6f"))  # unmasked: a client must never send that
        with self.assertRaises(ts.WebSocketError):
            connection.recv(timeout=5)


class StreamServer:
    """A stand-in for Truth Social's streaming endpoint: records each handshake, then refuses it or accepts."""

    def __init__(self, refuse=None):
        self.refuse = refuse  # (status, reason) to answer every handshake with
        self.requests = []  # (request line, headers) of every connection attempt
        self.connections = []
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.sock.settimeout(0.2)
        self.url = "ws://127.0.0.1:%d/api/v1/streaming" % self.sock.getsockname()[1]
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.closed:
            try:
                sock, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock.settimeout(5)
            line, headers, rest = ts._read_http_head(sock)
            self.requests.append((line, headers))
            if self.refuse:
                body = self.refuse[1].encode()
                sock.sendall(b"HTTP/1.1 %d %s\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n%s" % (
                    self.refuse[0], body, len(body), body))
                sock.close()
                continue
            sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\n\r\n" % ts._ws_accept(headers["sec-websocket-key"])).encode())
            self.connections.append(ts.WebSocket(sock, client=False, leftover=rest))

    def event(self, event, payload, as_text=True):
        message = {"stream": ["user"], "event": event, "payload": json.dumps(payload) if as_text else payload}
        self.connections[-1].send(json.dumps(message))

    def close(self):
        self.closed = True
        self.sock.close()
        for connection in self.connections:
            connection.sock.close()


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.delivered, self.logs = [], []

    def start(self, server, channel="user"):
        self.addCleanup(server.close)
        stream = ts.TruthStream(channel, "tok123", lambda status, name: self.delivered.append((status["id"], name)),
                                log=self.logs.append, user_agent="TestBrowser/1.0", url=server.url)
        self.addCleanup(stream.close)
        stream.start()
        return stream

    def test_only_new_posts_by_the_account_are_delivered(self):
        server = StreamServer()
        stream = self.start(server, channel="public:local")
        self.assertTrue(wait_until(lambda: stream.connected and server.connections))
        line, headers = server.requests[0]
        self.assertEqual(line, "GET /api/v1/streaming?access_token=tok123&stream=public%3Alocal HTTP/1.1")
        self.assertEqual(headers["authorization"], "Bearer tok123")
        self.assertEqual(headers["user-agent"], "TestBrowser/1.0")
        self.assertEqual(headers["origin"], "https://truthsocial.com")
        self.assertEqual((headers["upgrade"], headers["sec-websocket-version"]), ("websocket", "13"))

        stranger = make_status(501, T0)
        stranger["account"] = {"id": "999", "acct": "someone"}
        stranger["in_reply_to_account_id"] = ts.ACCOUNT_ID  # mentions the id, but is not his post
        server.event("update", stranger)
        server.event("notification", {"type": "mention", "status": make_status(502, T0)})
        server.event("delete", "503")
        server.connections[-1].send("not json at all " + ts.ACCOUNT_ID)
        server.event("update", make_status(504, T0))
        server.event("update", make_status(505, T0), as_text=False)
        self.assertTrue(wait_until(lambda: len(self.delivered) == 2))
        self.assertEqual(self.delivered, [("504", "public:local"), ("505", "public:local")])
        stream.close()
        self.assertTrue(wait_until(lambda: not stream.is_alive()))
        self.assertTrue(any("connected" in line for line in self.logs))

    def test_a_rejected_token_ends_the_stream_without_retrying(self):
        server = StreamServer(refuse=(401, "Unauthorized"))
        stream = self.start(server)
        self.assertTrue(wait_until(lambda: not stream.is_alive()))
        self.assertEqual(len(server.requests), 1)
        self.assertTrue(any("rejected the access token (HTTP 401)" in line for line in self.logs))
        self.assertFalse(any("tok123" in line for line in self.logs))  # the token never reaches the log

    def test_other_refusals_are_retried_with_a_pause(self):
        server = StreamServer(refuse=(503, "busy"))
        with mock.patch.object(ts.TruthStream, "RETRY_WAITS", (0.05,)):
            stream = self.start(server)
            self.assertTrue(wait_until(lambda: len(server.requests) >= 3))
        stream.close()
        self.assertTrue(any("refused (HTTP 503 busy); reconnecting" in line for line in self.logs))

    def test_reconnects_after_the_connection_drops(self):
        server = StreamServer()
        with mock.patch.object(ts.TruthStream, "RETRY_WAITS", (0.05,)):
            stream = self.start(server)
            self.assertTrue(wait_until(lambda: len(server.connections) == 1))
            server.connections[0].sock.close()
            self.assertTrue(wait_until(lambda: len(server.connections) == 2 and stream.connected))
            server.event("update", make_status(601, T0))
            self.assertTrue(wait_until(lambda: self.delivered == [("601", "user")]))
        self.assertTrue(any("reconnecting" in line for line in self.logs))

    def test_an_error_message_from_the_server_ends_the_stream(self):
        server = StreamServer()
        stream = self.start(server)
        self.assertTrue(wait_until(lambda: len(server.connections) == 1))
        server.connections[0].send(json.dumps({"error": "Access token does not cover required scopes", "status": 401}))
        self.assertTrue(wait_until(lambda: not stream.is_alive()))
        self.assertEqual(len(server.requests), 1)
        self.assertTrue(any("does not cover required scopes" in line for line in self.logs))

    def test_a_failing_delivery_does_not_end_the_stream(self):
        server = StreamServer()
        self.addCleanup(server.close)
        seen = []

        def deliver(status, channel):
            seen.append(status["id"])
            if len(seen) == 1:
                raise RuntimeError("database is busy")

        stream = ts.TruthStream("user", "tok123", deliver, log=self.logs.append, url=server.url)
        self.addCleanup(stream.close)
        stream.start()
        self.assertTrue(wait_until(lambda: len(server.connections) == 1))
        server.event("update", make_status(701, T0))
        server.event("update", make_status(702, T0))
        self.assertTrue(wait_until(lambda: seen == ["701", "702"]))
        self.assertTrue(any("could not handle post 701" in line for line in self.logs))

    def test_refused_handshake_reports_status_and_text(self):
        server = StreamServer(refuse=(403, "<html><body><h1>Sorry, you have been blocked</h1></body></html>"))
        self.addCleanup(server.close)
        with self.assertRaises(ts.WebSocketRefused) as caught:
            ts.ws_connect(server.url)
        self.assertEqual(caught.exception.status, 403)
        self.assertIn("Sorry, you have been blocked", str(caught.exception))
        with self.assertRaises(ts.WebSocketError):
            ts.ws_connect("https://truthsocial.com/")  # not a websocket address
        with self.assertRaises(ts.WebSocketError):
            ts.ws_connect(server.url, {"X-Test": "a\r\nInjected: 1"})


class FeedServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ts.FeedServer("127.0.0.1", 0)
        self.addCleanup(self.server.close)
        self.url = "ws://%s:%d/" % self.server.address

    def test_every_client_gets_every_message(self):
        first, second = ts.ws_connect(self.url), ts.ws_connect(self.url)
        self.assertEqual(self.server.clients(), 2)  # registered by the time the handshake is answered
        big = json.dumps({"text": "“quote” " * 20000})
        for message in ('{"id": "1"}', big, '{"id": "3"}'):
            self.server.publish(message)
        for client in (first, second):
            self.assertEqual([client.recv(timeout=5) for _ in range(3)], ['{"id": "1"}', big, '{"id": "3"}'])
        first.close()
        self.assertTrue(wait_until(lambda: self.server.clients() == 1))
        self.server.publish('{"id": "4"}')
        self.assertEqual(second.recv(timeout=5), '{"id": "4"}')
        second.send("clients may talk; nothing happens")
        second.ping()
        self.server.publish('{"id": "5"}')
        self.assertEqual(second.recv(timeout=5), '{"id": "5"}')
        second.close()

    def test_a_plain_http_request_gets_an_explanation(self):
        with socket.create_connection(self.server.address, timeout=5) as sock:
            sock.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            answer = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                answer += chunk
        self.assertTrue(answer.startswith(b"HTTP/1.1 426 Upgrade Required\r\n"))
        self.assertIn(b"websocket feed", answer)
        self.assertEqual(self.server.clients(), 0)

    def test_a_client_that_stops_reading_is_dropped_without_blocking(self):
        client = ts.ws_connect(self.url)
        self.assertEqual(self.server.clients(), 1)
        started = time.time()
        for number in range(1200):  # more than its queue holds, and nobody is reading
            self.server.publish("x" * 20000)
        self.assertLess(time.time() - started, 5)
        self.assertTrue(wait_until(lambda: self.server.clients() == 0))
        client.sock.close()

    def test_closing_the_server_disconnects_clients(self):
        client = ts.ws_connect(self.url)
        self.addCleanup(client.sock.close)
        self.server.close()
        with self.assertRaises(ts.WebSocketError):
            for _ in range(5):
                client.recv(timeout=5)
        with self.assertRaises(ts.ScrapeError):
            taken = socket.create_server(("127.0.0.1", 0))
            self.addCleanup(taken.close)
            ts.FeedServer("127.0.0.1", taken.getsockname()[1])


class WatchStreamTests(WatchTests):
    """ts.watch() with the streaming websocket switched on (the streams themselves are simulated)."""

    def setUp(self):
        super().setUp()
        self.started, self.closed = [], []

    def start_stream(self, channel, token, deliver, log, user_agent):
        self.started.append((channel, token))
        self.deliver = deliver
        return types.SimpleNamespace(close=lambda: self.closed.append(channel))

    def test_a_pushed_post_is_reported_at_once_and_only_once(self):
        self.seed()

        def push():
            self.api.add(2000, age_days=0)
            self.assertEqual(self.reported, [])
            self.deliver(self.api.posts[2000], "user")
            self.assertEqual(self.reported, [([2000], True)])  # reported before any poll ran
            self.deliver(self.api.posts[2000], "public:local")  # the second stream brings the same post

        def poll_only():
            self.api.add(2001, age_days=0)  # one the streams missed

        self.watch([push, poll_only, None], token="tok", start_stream=self.start_stream)
        self.assertEqual(self.reported, [([2000], True), ([2001], True)])
        self.assertEqual(self.sources, ["stream:user", "poll"])
        self.assertEqual(self.started, [("user", "tok"), ("public:local", "tok")])  # after the first poll
        self.assertEqual(self.closed, ["user", "public:local"])
        self.assertEqual(self.stored_ids(), list(range(1010, 1030)) + [2000, 2001])

    def test_pushed_posts_out_of_order_are_all_reported(self):
        self.seed()

        def push():
            for post_id in (2000, 2001, 2002):
                self.api.add(post_id, age_days=0)
            self.deliver(self.api.posts[2002], "user")  # 2000 and 2001 never came over the stream
            self.deliver(self.api.posts[1029], "user")  # an old post again: not news

        self.watch([push, None], token="tok", start_stream=self.start_stream)
        self.assertEqual(self.reported, [([2002], True), ([2000, 2001], True)])
        self.assertEqual(self.sources, ["stream:user", "poll"])

    def test_a_pushed_post_survives_a_failing_report(self):
        self.seed()
        calls = []

        def on_new(posts, live, source):
            calls.append(([p.id for p in posts], source))
            if len(calls) == 1:
                raise OSError("disk full")

        polls = []

        def on_poll(error):
            polls.append(error)
            if len(polls) == 1:
                self.api.add(2000, age_days=0)
                with self.assertRaises(OSError):
                    self.deliver(self.api.posts[2000], "user")

        ts.watch(self.db, on_new=on_new, on_poll=on_poll, log=self.logs.append, token="tok",
                 start_stream=self.start_stream, should_stop=lambda: len(polls) == 2, connect=self.connect,
                 clock=lambda: self.now, sleep=self.tick)
        self.assertEqual(calls, [([2000], "stream:user"), ([2000], "poll")])  # the poll made up for it

    def test_no_token_means_no_streams(self):
        self.seed()
        self.watch([None], start_stream=self.start_stream)
        self.assertEqual(self.started, [])
        self.watch([None], token="tok", streams=("user",), start_stream=self.start_stream)
        self.assertEqual(self.started, [("user", "tok")])

    def test_streams_are_not_used_when_following_or_remote(self):
        self.seed()
        with ts.UpdateLock(self.db):
            self.watch([None], token="tok", start_stream=self.start_stream)
        ts.load_remote.return_value = {"ssh": "box", "dir": "/srv/scraper", "python": "python3", "wrap": ""}
        with mock.patch.object(ts, "run_update", lambda *args, **kw: None):
            self.watch([None], token="tok", start_stream=self.start_stream)
        self.assertEqual(self.started, [])


class TokenTests(unittest.TestCase):
    def token(self, env=None, config=None):
        with mock.patch.dict(os.environ, {} if env is None else {"TRUTHSOCIAL_TOKEN": env}), \
                mock.patch.object(ts, "_load_config", return_value={} if config is None else {"token": config}):
            if env is None:
                os.environ.pop("TRUTHSOCIAL_TOKEN", None)
            return ts.load_token()

    def test_where_the_token_comes_from(self):
        self.assertIsNone(self.token())
        self.assertEqual(self.token(config="abc-DEF_123"), "abc-DEF_123")
        self.assertEqual(self.token(env=" fromenv \n", config="fromconfig"), "fromenv")
        for bad in ("two words", "line\nbreak", 12345):
            with self.assertRaises(ts.ScrapeError):
                self.token(config=bad)


if __name__ == "__main__":
    unittest.main()
