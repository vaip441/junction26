"""Add every market in markets.txt to a running terminal.

    uv run --env-file .env python scripts/seed_markets.py http://127.0.0.1:18911

markets.txt: one market link per line, optionally followed by a space and the polling interval in seconds.
"""
import os
import sys

import httpx

base = sys.argv[1].rstrip("/")
headers = {"X-Terminal-Key": os.environ.get("TERMINAL_KEY", "")}
for line in open("markets.txt"):
    parts = line.split()
    if not parts or parts[0].startswith("#"):
        continue
    body = {"query": parts[0], **({"poll_seconds": int(parts[1])} if len(parts) > 1 else {})}
    r = httpx.post(f"{base}/markets", json=body, headers=headers, timeout=120)
    d = r.json()
    print(r.status_code, d.get("id") or d.get("detail"), "|", d.get("title", ""), "|", d.get("price", ""))
