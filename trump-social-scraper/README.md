# trump-social-scraper

Watches @realDonaldTrump on Truth Social and hands every new post to other programs the moment it is
seen: over a local websocket, as JSON lines on stdout, or appended to a file. Posts are also stored
in a SQLite database that can be searched by keyword.

One file, `trump_scraper.py`. Python 3.9+, standard library only. It is separate from `terminal/`
and nothing in `terminal/` imports it.

## How fast it is

| Mode | Delay after he posts | Needs |
| --- | --- | --- |
| Polling (default) | up to the poll interval (20 s; 10 s at the fastest) plus about half a second for the request | FlareSolverr |
| Truth Social's streaming websocket | pushed by Truth Social as the post is made | FlareSolverr and the access token of a Truth Social account |

Truth Social's streaming websocket (`wss://truthsocial.com/api/v1/streaming`) refuses anonymous
connections: without a valid access token it answers HTTP 401. So without a token the scraper polls.

**The streaming path has not been run with a real token.** The websocket client is tested against
an independent websocket library and against the real endpoint as far as the 401. Whether the
`user` and `public:local` channels carry his posts, and how quickly, is unverified until someone
runs it with a token. Polling keeps running underneath either way, so a post the stream misses is
still reported within one poll interval.

## Setup

Truth Social sits behind Cloudflare, which rejects plain HTTP clients, so every request goes through
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr), which drives a real Chrome.

On Linux, install Chrome (or Chromium) and Xvfb, then put FlareSolverr's source next to the script:

```sh
cd trump-social-scraper
mkdir flaresolverr && cd flaresolverr
curl -L https://github.com/FlareSolverr/FlareSolverr/archive/refs/tags/v3.5.2.tar.gz | tar xz
python3 -m venv venv
venv/bin/pip install -r FlareSolverr-3.5.2/requirements.txt
```

The scraper starts that copy by itself when nothing answers on `127.0.0.1:8191`, binds it to
localhost only, and shuts it down with its Chrome when the run ends. The precompiled FlareSolverr
release did not start on Ubuntu 26.04; the source install above did.

Anywhere else (Windows included), run a FlareSolverr yourself and pass its address with
`--flaresolverr URL` or `$FLARESOLVERR_URL`.

## Live feed

```sh
python trump_scraper.py watch --serve 8770 --jsonl data/feed.jsonl
```

- `--serve [HOST:]PORT` pushes each new post to every connected websocket client as one JSON text
  message. Host defaults to `127.0.0.1`. Clients only listen.
- `--jsonl FILE` appends each new post to a file, one JSON object per line.
- `--json` prints the posts as JSON lines on stdout and everything else on stderr, for piping.
- `--interval SEC` sets the poll interval (default 20, minimum 10).
- Keywords narrow what is reported, with the rules of `search`: `watch "tariff*" china --any`.
  Every post is stored regardless.

A client:

```python
import json
from websockets.sync.client import connect

with connect("ws://127.0.0.1:8770/") as feed:
    for message in feed:
        post = json.loads(message)
        print(post["created_at"], post["source"], post["text"])
```

The shape of one message (the times here are made up for the example):

```json
{
  "id": "117611608680849019",
  "created_at": "2026-11-13T22:58:48.161Z",
  "detected_at": "2026-11-13T22:59:01.329Z",
  "delay_seconds": 13.168,
  "live": true,
  "source": "poll",
  "type": "post",
  "retruth_of": null,
  "text": "Thank you to the United States Coast Guard ...",
  "quote_of": null,
  "quote_text": null,
  "link_title": null,
  "link_url": null,
  "media": [],
  "url": "https://truthsocial.com/@realDonaldTrump/117611608680849019"
}
```

| Field | Meaning |
| --- | --- |
| `id` | Truth Social's post id, as a string |
| `created_at` | when Truth Social says it was posted (UTC) |
| `detected_at` | when this scraper saw it (UTC, this machine's clock) |
| `delay_seconds` | `detected_at` minus `created_at` |
| `live` | `false` for posts made while no watch was running, or found on the first poll after a failed one; these can be old |
| `source` | `poll`, or `stream:<channel>` for a post pushed by Truth Social's websocket |
| `type` | `post` or `retruth` |
| `retruth_of` | for a retruth, the account that wrote it; `text` is then that account's text |
| `quote_of`, `quote_text` | the quoted post, if he quoted one |
| `link_title`, `link_url` | the link preview, if any |
| `media` | URLs of attached pictures and videos |

Each post is sent once per run. Posts made while the watch was down are sent when it starts again,
with `"live": false`. A post can also be sent a second time after a restart (one that arrived over
the stream just before the watch was stopped), so deduplicate on `id` if you keep state across
restarts.

## Streaming with a token

Put the access token of a Truth Social account in `$TRUTHSOCIAL_TOKEN`, or in `config.json` next to
the script:

```json
{"token": "..."}
```

The token is the `Authorization: Bearer ...` value the logged-in web app sends with its
`/api/v1/...` requests. `watch` then also listens to two channels:

- `user`: the home timeline of the token's account, which must follow @realDonaldTrump;
- `public:local`: every public post on the site, of which only his are kept.

Pick others with `--stream CHANNEL`; turn streaming off with `--no-stream`. A rejected token is
reported once in the log and the watch goes on polling.

`config.json` is git-ignored. Keep the token out of the repository.

## Search

```sh
python trump_scraper.py search tariff
python trump_scraper.py search "tariff*" china                 # both; tariff* also finds tariffs
python trump_scraper.py search "fake news" --since 2025-01-20
python trump_scraper.py search iran israel --any --type original --sort likes
python trump_scraper.py search biden --exclude sleepy --export biden.csv
python trump_scraper.py ui          # search page in the browser, kept up to date
python trump_scraper.py status      # what is stored
python trump_scraper.py update      # fetch new posts once, without watching
```

Keywords match whole words in any capitalisation. `--help` on any command lists the rest.

## Scraping on another machine

If `config.json` names a `remote`, updates run there over ssh and the database is downloaded from
it; searching happens locally. The remote needs this folder with FlareSolverr set up as above.

```json
{"remote": {"ssh": "host", "dir": "/path/to/trump-social-scraper", "python": "/usr/bin/python3", "wrap": "nice"}}
```

## Limits

- Truth Social blocks an address for about a minute after roughly 8 requests in a minute. The
  default poll uses 3 a minute; `--interval` will not go below 10 s.
- Only posts from the first run on are stored. `update --history` downloads the older ones (hours).
- Posts that are only a picture or video have no text to search.
- A retruth's like and reply counts are those of the retruth itself, not of the original post.
- Deleted posts stay in the database.
- Like, retruth and reply counts are as of the last time the post was read: a watch re-reads the
  newest 20 on every poll, and `update` re-reads everything from the last three days.

## Tests

```sh
python -m unittest test_trump_scraper
```

No network needed.
