"""Throwaway first-hour test of Context.dev search and scrape. Run: uv run --env-file .env python scripts/spike.py"""
import json
import os
import sys
import time

import httpx

API = "https://api.context.dev/v1"
H = {"Authorization": f"Bearer {os.environ['CONTEXT_DEV_API_KEY']}"}


def post(path, body):
    t = time.time()
    r = httpx.post(API + path, headers=H, json=body, timeout=120)
    return r.status_code, r.json(), time.time() - t


def show(label, body, save=None):
    code, d, t = post("/web/search", body)
    if save:
        json.dump(d, open(save, "w"), indent=1)
    rs = d.get("results") or []
    print(f"\n== {label}: HTTP {code}, {len(rs)} results, {t:.1f}s, credits {d.get('key_metadata')}, partial {d.get('partial')}")
    if code != 200:
        print("  ", json.dumps(d)[:300])
    for r in rs[:8]:
        print(f"   {r.get('url', '')[:90]} | {r.get('title', '')[:70]}")
    if rs:
        print("   result keys:", sorted(rs[0].keys()))
    return rs


Q = "Jensen Huang Nvidia CEO step down"
news = show("news, last 24h", {"query": Q, "freshness": "last_24_hours", "numResults": 10}, "tests/fixtures/search_response.json")
show("reddit, last 24h", {"query": Q, "freshness": "last_24_hours", "includeDomains": ["reddit.com"], "numResults": 10})
show("reddit, last week", {"query": Q, "freshness": "last_week", "includeDomains": ["reddit.com"], "numResults": 10})
show("x.com, last 24h", {"query": Q, "freshness": "last_24_hours", "includeDomains": ["x.com", "twitter.com"], "numResults": 10})
show("x.com, last week", {"query": Q, "freshness": "last_week", "includeDomains": ["x.com", "twitter.com"], "numResults": 10})
show("venues, plain words", {"query": "will jensen get fired", "includeDomains": ["polymarket.com", "kalshi.com"], "numResults": 10})
show("wikipedia", {"query": "Jensen Huang", "includeDomains": ["wikipedia.org"], "numResults": 10})
if news:
    code, d, t = post("/web/scrape", {"url": news[0]["url"], "formats": {"markdown": True}, "sharedParams": {"mainContentOnly": True}})
    print(f"\n== scrape {news[0]['url'][:80]}: HTTP {code}, {t:.1f}s, credits {d.get('key_metadata')}")
    print("   top keys:", sorted(d.keys()))
    print("   metadata:", json.dumps(d.get("metadata"))[:600])
    print("   markdown chars:", len(((d.get("markdown") or {}).get("data")) or ""))
