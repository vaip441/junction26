#!/usr/bin/env python3
"""Trump Truth Social scraper with keyword search and a live feed.

Scrapes @realDonaldTrump's posts straight from truthsocial.com. Truth Social sits
behind a Cloudflare check that rejects plain HTTP clients, so every request goes
through a FlareSolverr server (https://github.com/FlareSolverr/FlareSolverr),
which drives a real Chrome. Posts are stored in a SQLite database and can be
searched by keyword from the command line or from a local web page.

    python trump_scraper.py watch                  # live: report every new post as it appears
    python trump_scraper.py watch tariff* china    # ... only posts with these keywords
    python trump_scraper.py update                 # fetch new posts once
    python trump_scraper.py search tariff* china   # keyword search of what is stored
    python trump_scraper.py ui                     # search page in the browser, kept up to date
    python trump_scraper.py status                 # what is in the database

Only posts made from the first run on are collected; `update --history` downloads
the older ones too.

Scraping can run on another machine: if config.json names a "remote" (an ssh host
with this script and FlareSolverr on it), updates run there and the database is
downloaded from it; searching happens here.

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import base64
import collections
import csv
import hashlib
import html
import json
import os
import queue
import re
import shlex
import signal
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DEFAULT_DB = DATA_DIR / "truths.db"
CONFIG_PATH = APP_DIR / "config.json"
SNAPSHOT_NAME = "truths.snapshot.db"
DEFAULT_FS_URL = "http://127.0.0.1:8191"
EXIT_BUSY = 3  # exit code of `update` when another update holds the lock

ACCOUNT_ID = "107780257626128497"  # @realDonaldTrump
ACCOUNT_HANDLE = "realDonaldTrump"
STATUSES_URL = "https://truthsocial.com/api/v1/accounts/" + ACCOUNT_ID + "/statuses"
PAGE_LIMIT = 20  # the most Truth Social returns per request
DEFAULT_INTERVAL = 8.0  # seconds between requests; measured limit is about 8 requests a minute

# Every one-off update re-reads posts younger than this, so their like/retruth counts settle.
REFRESH_WINDOW = 3 * 86400

# Live watching: one request per poll.
WATCH_INTERVAL = 20.0  # seconds between polls when scraping here (3 requests a minute)
REMOTE_WATCH_INTERVAL = 60.0  # ... when every poll is an ssh round trip to the scraping machine
MIN_WATCH_INTERVAL = 10.0  # faster than this runs into Truth Social's rate limit
SESSION_LIFETIME = 3600.0  # a long watch restarts its browser this often, so it cannot bloat


class ScrapeError(RuntimeError):
    """Scraping failed in a way the user should be told about."""


class UpdateBusy(ScrapeError):
    """Another update is already running on this database."""


class _Stopped(Exception):
    """Raised inside a watch when it has been asked to stop."""


# --------------------------------------------------------------------------
# FlareSolverr
# --------------------------------------------------------------------------

# FlareSolverr is local: never send these requests through a system proxy.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_flaresolverr_command():
    """How to launch the FlareSolverr installed under ./flaresolverr, as an argv list - or None.

    Either a source checkout (./flaresolverr/<name>/src/flaresolverr.py, run with
    ./flaresolverr/venv when that exists) or a release binary (./flaresolverr[/<name>]/flaresolverr).
    """
    root = APP_DIR / "flaresolverr"
    for script in sorted(root.glob("*/src/flaresolverr.py")):
        python = root / "venv" / "bin" / "python"
        return [str(python) if python.is_file() else sys.executable, str(script)]
    for binary in [root / "flaresolverr"] + sorted(root.glob("*/flaresolverr")):
        if binary.is_file() and os.access(binary, os.X_OK):
            return [str(binary)]
    return None


class FlareSolverr:
    """Minimal client for a FlareSolverr server.

    On Linux/macOS, when nothing answers at the address, the copy installed in
    ./flaresolverr is started for the duration of the run and shut down afterwards
    together with the Chrome and Xvfb processes it spawned.
    """

    def __init__(self, url=None, log=None):
        self.url = (url or os.environ.get("FLARESOLVERR_URL") or DEFAULT_FS_URL).rstrip("/")
        self.log = log or (lambda message: None)
        self.session = None
        self.user_agent = None
        self.proc = None
        self.pgid = None  # process group of a FlareSolverr this run owns and must stop
        self._log_file = None
        self._pid_path = DATA_DIR / "flaresolverr.pid"

    def __enter__(self):
        try:
            self.start()
            self.open_session()
        except BaseException:
            self.close()  # never leave a server we launched running
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def _call(self, payload, timeout):
        request = urllib.request.Request(
            self.url + "/v1",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with _LOCAL.open(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:  # FlareSolverr reports failures as HTTP 500 + JSON
            body = error.read()
        except OSError as error:  # refused, reset, timed out
            raise ScrapeError("cannot reach FlareSolverr at %s (%s)" % (self.url, error)) from None
        try:
            data = json.loads(body)
        except ValueError:
            raise ScrapeError("unexpected reply from FlareSolverr: %r" % body[:200]) from None
        if not isinstance(data, dict) or data.get("status") != "ok":
            message = data.get("message") if isinstance(data, dict) else None
            raise ScrapeError("FlareSolverr: %s" % (message or "unknown error"))
        return data

    def is_up(self):
        try:
            with _LOCAL.open(self.url + "/", timeout=5) as response:
                return "FlareSolverr" in str(json.loads(response.read()).get("msg", ""))
        except Exception:
            return False

    def start(self):
        """Make sure a FlareSolverr server is answering, launching the bundled one if needed."""
        if self.is_up():
            self._adopt_leftover()
            return
        target = urllib.parse.urlsplit(self.url)
        command = find_flaresolverr_command()
        if os.name == "nt" or command is None or target.hostname not in ("127.0.0.1", "localhost"):
            raise ScrapeError(
                "FlareSolverr is not answering at %s.\n"
                "Start one (https://github.com/FlareSolverr/FlareSolverr) and pass its address with --flaresolverr, "
                "or put a \"remote\" scrape machine in config.json. On Linux, a copy installed in %s "
                "is started automatically." % (self.url, APP_DIR / "flaresolverr"))
        self.log("Starting FlareSolverr ...")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / "flaresolverr.log"
        self._log_file = open(log_path, "wb")
        # HOST=127.0.0.1: FlareSolverr must never be reachable from other machines.
        # HOME: keeps the chromedriver it downloads and Chrome's caches inside ./data.
        home = DATA_DIR / "flaresolverr-home"
        home.mkdir(exist_ok=True)
        env = dict(os.environ, HOST="127.0.0.1", PORT=str(target.port or 80), LOG_LEVEL="info", HOME=str(home))
        self.proc = subprocess.Popen(
            command,
            cwd=str(Path(command[-1]).parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group: lets close() stop FlareSolverr AND its browser
        )
        self.pgid = self.proc.pid
        self._pid_path.write_text(str(self.pgid))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.close()
                raise ScrapeError("FlareSolverr exited while starting; see %s" % log_path)
            if self.is_up():
                return
            time.sleep(1)
        self.close()
        raise ScrapeError("FlareSolverr did not become ready within 120 s; see %s" % log_path)

    def _adopt_leftover(self):
        """If the FlareSolverr that is answering was left behind by an earlier run of this script
        that got killed, own it so it is shut down at the end. Identified by its exact command line."""
        command = find_flaresolverr_command()
        try:
            pid = int(self._pid_path.read_text().strip())
            running = Path("/proc/%d/cmdline" % pid).read_bytes().rstrip(b"\0").split(b"\0")
            if command and running == [os.fsencode(word) for word in command] and os.getpgid(pid) == pid:
                self.pgid = pid
        except (OSError, ValueError, AttributeError):
            pass

    def _stop_server(self):
        """Stop the FlareSolverr this run owns: its whole process group, politely, then firmly."""
        if self.pgid is None:
            return
        pgid, self.pgid = self.pgid, None
        for sig, grace in ((signal.SIGTERM, 15), (signal.SIGKILL, 5)):
            try:
                os.killpg(pgid, sig)
            except OSError:
                break  # nothing left in the group
            deadline = time.monotonic() + grace
            gone = False
            while time.monotonic() < deadline and not gone:
                if self.proc is not None:
                    self.proc.poll()  # reap, so a finished leader does not linger as a zombie
                try:
                    os.killpg(pgid, 0)
                    time.sleep(0.2)
                except OSError:
                    gone = True
            if gone:
                break
        self.proc = None
        try:
            self._pid_path.unlink()
        except OSError:
            pass

    def open_session(self):
        """One browser for the whole run, so the Cloudflare check is solved once."""
        self.session = self._call({"cmd": "sessions.create"}, 120)["session"]

    def close_session(self):
        if self.session:
            session, self.session = self.session, None
            try:
                self._call({"cmd": "sessions.destroy", "session": session}, 60)
            except ScrapeError:
                pass

    def get(self, url, max_timeout=60):
        payload = {"cmd": "request.get", "url": url, "maxTimeout": int(max_timeout * 1000)}
        if self.session:
            payload["session"] = self.session
        solution = self._call(payload, max_timeout + 30).get("solution")
        if not isinstance(solution, dict):
            raise ScrapeError("FlareSolverr returned no solution for %s" % url)
        if isinstance(solution.get("userAgent"), str) and solution["userAgent"]:
            self.user_agent = solution["userAgent"]  # the browser's own; reused for the streaming websocket
        return solution

    def close(self):
        self.close_session()
        self._stop_server()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None


# --------------------------------------------------------------------------
# Truth Social
# --------------------------------------------------------------------------

_PRE_RE = re.compile(r"<pre[^>]*>(.*)</pre>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_json(page):
    """Recover the JSON document from the page Chrome renders for a JSON response."""
    match = _PRE_RE.search(page)
    body = html.unescape(match.group(1)) if match else page
    try:
        return json.loads(body)
    except ValueError:
        visible = " ".join(html.unescape(_TAG_RE.sub(" ", page)).split())
        raise ScrapeError("Truth Social did not return JSON: %s" % (visible[:200] or "(empty page)")) from None


def check_statuses(data):
    """Validate one page of the statuses API; returns the list of status objects."""
    if isinstance(data, dict):
        message = data.get("error") or data.get("errors") or data
        raise ScrapeError("Truth Social API error: %s" % (message,))
    if not isinstance(data, list):
        raise ScrapeError("Truth Social API returned %s instead of a list" % type(data).__name__)
    for status in data:
        if not isinstance(status, dict) or not str(status.get("id", "")).isdigit() or not status.get("created_at"):
            raise ScrapeError("Truth Social API returned a malformed post: %r" % (str(status)[:200],))
        account = status.get("account") or {}
        if str(account.get("id")) != ACCOUNT_ID:
            raise ScrapeError(
                "Truth Social API returned a post from account %r, expected @%s"
                % (account.get("acct") or account.get("id"), ACCOUNT_HANDLE)
            )
    return data


def _is_rate_limit(error):
    """Cloudflare's temporary block page (as FlareSolverr reports it) or an API 'too many requests'."""
    message = str(error).lower()
    return "blocked" in message or "too many" in message or "rate limit" in message


class TruthSocial:
    """Reads @realDonaldTrump's timeline through FlareSolverr: paced, with retries and back-off.

    Truth Social allows roughly 8 requests a minute per address and answers more with a
    block that lasts about a minute, so requests are spaced `interval` seconds apart; if a
    block still happens, the client waits it out and widens the spacing for the rest of the run.
    """

    ERROR_WAITS = (10, 30, 90)
    BLOCK_WAITS = (90, 300, 900, 1800)
    MAX_INTERVAL = 60.0

    def __init__(self, solver, interval=DEFAULT_INTERVAL, log=None, sleep=time.sleep, clock=time.monotonic):
        self.solver = solver
        self.interval = max(0.0, float(interval))
        self.log = log or (lambda message: None)
        self.sleep = sleep
        self.clock = clock
        self._last_request = None

    def _pace(self):
        if self._last_request is not None:
            wait = self._last_request + self.interval - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()

    def _wait(self, seconds, why):
        """A long pause that keeps reporting (so a watcher - or a dropped ssh pipe - notices)."""
        remaining = seconds
        while remaining > 0:
            self.log("%s - waiting %d s" % (why, remaining))
            step = min(30, remaining)
            self.sleep(step)
            remaining -= step

    def fetch_page(self, max_id=None):
        """Up to PAGE_LIMIT posts older than max_id (newest posts when max_id is None), newest first."""
        params = {"limit": PAGE_LIMIT}
        if max_id is not None:
            params["max_id"] = str(max_id)
        url = STATUSES_URL + "?" + urllib.parse.urlencode(params)
        errors = blocks = 0
        while True:
            self._pace()
            try:
                solution = self.solver.get(url)
                return check_statuses(extract_json(solution.get("response") or ""))
            except ScrapeError as error:
                if _is_rate_limit(error):
                    if blocks == len(self.BLOCK_WAITS):
                        raise ScrapeError("Truth Social keeps blocking requests; try again later (%s)" % error) from None
                    self.interval = min(self.MAX_INTERVAL, max(2.0, self.interval) * 1.5)
                    self._wait(self.BLOCK_WAITS[blocks], "Rate-limited by Truth Social (now pacing %.0f s)" % self.interval)
                    blocks += 1
                else:
                    if errors == len(self.ERROR_WAITS):
                        raise ScrapeError("%s (gave up after %d attempts)" % (error, errors + 1)) from None
                    self._wait(self.ERROR_WAITS[errors], str(error))
                    errors += 1
                try:  # a fresh browser gets a fresh Cloudflare check
                    self.solver.close_session()
                    self.solver.open_session()
                except ScrapeError:
                    pass


# --------------------------------------------------------------------------
# Websockets (RFC 6455): just enough for Truth Social's stream and the local feed
# --------------------------------------------------------------------------

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_WS_TEXT, _WS_BINARY, _WS_CLOSE, _WS_PING, _WS_PONG = 0x1, 0x2, 0x8, 0x9, 0xA
_WS_MAX_MESSAGE = 16 * 1024 * 1024


class WebSocketError(ScrapeError):
    """The websocket connection failed, ended, or the other side broke the protocol."""


class WebSocketRefused(WebSocketError):
    """The server answered the websocket handshake with an HTTP error."""

    def __init__(self, status, detail):
        super().__init__("HTTP %d%s" % (status, " " + detail if detail else ""))
        self.status = status


def _ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")


def _ws_mask(payload, key):
    """XOR the payload with the repeating 4-byte key (the same operation masks and unmasks)."""
    if not payload:
        return b""
    repeated = (key * (len(payload) // 4 + 1))[:len(payload)]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(repeated, "big")).to_bytes(len(payload), "big")


def _ws_frame(opcode, payload=b"", mask=False):
    """One complete (unfragmented) frame."""
    length = len(payload)
    head = bytearray([0x80 | opcode])
    flag = 0x80 if mask else 0
    if length < 126:
        head.append(flag | length)
    elif length < 65536:
        head.append(flag | 126)
        head += struct.pack("!H", length)
    else:
        head.append(flag | 127)
        head += struct.pack("!Q", length)
    if mask:
        key = os.urandom(4)
        return bytes(head) + key + _ws_mask(payload, key)
    return bytes(head) + payload


def _read_http_head(sock, limit=16384):
    """Read up to the blank line -> (start line, {lower-case header: value}, bytes read past it)."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WebSocketError("connection closed during the handshake")
        data += chunk
        if len(data) > limit:
            raise WebSocketError("the handshake is too long")
    head, rest = data.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, colon, value = line.partition(":")
        if colon:
            headers[name.strip().lower()] = value.strip()
    return lines[0], headers, rest


class WebSocket:
    """An established websocket connection, for either end.

    recv() belongs to one thread; send() and ping() may be called from any thread.
    """

    def __init__(self, sock, client, leftover=b""):
        self.sock = sock
        self.client = client  # a client masks what it sends and receives unmasked frames; a server the reverse
        self.last_seen = time.monotonic()  # when anything at all (a ping counts) last arrived
        self._buffer = bytearray(leftover)
        self._parts = None  # payloads of the message being assembled from fragments
        self._kind = None
        self._send_lock = threading.Lock()
        self._closed = False

    def _send(self, opcode, payload=b""):
        with self._send_lock:
            self.sock.sendall(_ws_frame(opcode, payload, mask=self.client))

    def send(self, text):
        self._send(_WS_TEXT, text.encode("utf-8"))

    def ping(self):
        self._send(_WS_PING)

    def _take_frame(self):
        """Cut one whole frame out of the buffer -> (final, opcode, payload); None while it is incomplete."""
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        first, second = buffer[0], buffer[1]
        if first & 0x70:
            raise WebSocketError("received a frame using an extension that was never agreed")
        masked, length, offset = bool(second & 0x80), second & 0x7F, 2
        if length == 126:
            if len(buffer) < 4:
                return None
            length, offset = struct.unpack_from("!H", buffer, 2)[0], 4
        elif length == 127:
            if len(buffer) < 10:
                return None
            length, offset = struct.unpack_from("!Q", buffer, 2)[0], 10
        if length > _WS_MAX_MESSAGE:
            raise WebSocketError("received a frame of %d bytes, which is too large" % length)
        if masked == self.client:
            raise WebSocketError("received a frame with the wrong masking for this end of the connection")
        end = offset + (4 if masked else 0) + length
        if len(buffer) < end:
            return None
        payload = bytes(buffer[end - length:end])
        if masked:
            payload = _ws_mask(payload, bytes(buffer[offset:offset + 4]))
        del buffer[:end]
        return bool(first & 0x80), first & 0x0F, payload

    def recv(self, timeout=None):
        """The next message - str for text, bytes for binary - or None if none arrived within `timeout` seconds.

        Pings are answered from here. Raises WebSocketError once the connection has ended.
        """
        while True:
            frame = self._take_frame()
            if frame is None:
                try:
                    self.sock.settimeout(timeout)
                    data = self.sock.recv(65536)
                except socket.timeout:
                    return None
                except OSError as error:
                    raise WebSocketError("connection lost (%s)" % error) from None
                if not data:
                    raise WebSocketError("connection closed by the other side")
                self._buffer += data
                self.last_seen = time.monotonic()
                continue
            final, opcode, payload = frame
            if opcode == _WS_PONG:
                continue
            if opcode == _WS_PING:
                try:
                    self._send(_WS_PONG, payload)
                except OSError as error:
                    raise WebSocketError("connection lost (%s)" % error) from None
                continue
            if opcode == _WS_CLOSE:
                try:
                    self._send(_WS_CLOSE, payload[:2])
                except OSError:
                    pass
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                reason = payload[2:].decode("utf-8", "replace")
                raise WebSocketError("closed by the other side (code %d%s)" % (code, ": " + reason if reason else ""))
            if opcode in (_WS_TEXT, _WS_BINARY):
                self._kind, self._parts = opcode, [payload]
            elif opcode == 0 and self._parts is not None:
                self._parts.append(payload)
                if sum(len(part) for part in self._parts) > _WS_MAX_MESSAGE:
                    raise WebSocketError("received a message that is too large")
            else:
                raise WebSocketError("received an unexpected frame (type %d)" % opcode)
            if final:
                data, kind, self._parts = b"".join(self._parts), self._kind, None
                return data.decode("utf-8", "replace") if kind == _WS_TEXT else data

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._send(_WS_CLOSE, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def ws_connect(url, headers=None, timeout=30):
    """Open a websocket connection to a ws:// or wss:// address -> WebSocket.

    Raises WebSocketRefused when the server answers with an HTTP error, WebSocketError otherwise.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("ws", "wss") or not parts.hostname:
        raise WebSocketError("not a websocket address")
    secure = parts.scheme == "wss"
    default_port = 443 if secure else 80
    port = parts.port or default_port
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [
        "GET %s HTTP/1.1" % ((parts.path or "/") + ("?" + parts.query if parts.query else "")),
        "Host: %s" % (parts.hostname if port == default_port else "%s:%d" % (parts.hostname, port)),
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: " + key,
        "Sec-WebSocket-Version: 13",
    ]
    for name, value in (headers or {}).items():
        if "\r" in name + value or "\n" in name + value:
            raise WebSocketError("a header contains a line break")
        lines.append("%s: %s" % (name, value))
    try:
        sock = socket.create_connection((parts.hostname, port), timeout=timeout)
    except OSError as error:
        raise WebSocketError("cannot connect to %s (%s)" % (parts.hostname, error)) from None
    try:
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        status_line, answer, rest = _read_http_head(sock)
        try:
            status = int(status_line.split()[1])
        except (IndexError, ValueError):
            raise WebSocketError("%s did not answer with HTTP" % parts.hostname) from None
        if status != 101:
            if not rest:
                try:
                    sock.settimeout(2)
                    rest = sock.recv(2048)
                except OSError:
                    pass
            detail = " ".join(_TAG_RE.sub(" ", rest.decode("utf-8", "replace")).split())
            raise WebSocketRefused(status, detail[:120])
        if answer.get("sec-websocket-accept") != _ws_accept(key):
            raise WebSocketError("%s answered the handshake incorrectly" % parts.hostname)
        return WebSocket(sock, client=True, leftover=rest)
    except OSError as error:  # includes TLS failures and timeouts
        sock.close()
        raise WebSocketError("handshake with %s failed (%s)" % (parts.hostname, error)) from None
    except BaseException:
        sock.close()
        raise


# --------------------------------------------------------------------------
# Truth Social's streaming API: posts pushed over a websocket the moment they are made
# --------------------------------------------------------------------------

STREAM_URL = "wss://truthsocial.com/api/v1/streaming"
# "user" is the home timeline of the account the token belongs to (it must follow @realDonaldTrump);
# "public:local" is every public post on the site, of which only his are kept.
DEFAULT_STREAMS = ("user", "public:local")
STREAM_SILENCE = 90.0  # seconds without any traffic (a ping every 30 s is normal) before a connection counts as dead
FALLBACK_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36")


def stream_status(message):
    """The post in one message of the streaming API, if it announces a new @realDonaldTrump post; else None."""
    if ACCOUNT_ID not in message:  # cheap: nearly everything on a public stream is by someone else
        return None
    try:
        data = json.loads(message)
        if not isinstance(data, dict) or data.get("event") != "update":
            return None
        status = data.get("payload")
        if isinstance(status, str):
            status = json.loads(status)
        return check_statuses([status])[0]
    except (ValueError, ScrapeError):
        return None


def _stream_error(message):
    """The text of an error message from the streaming API ({"error": ...}), or None for anything else."""
    if '"error"' not in message[:200]:
        return None
    try:
        data = json.loads(message)
    except ValueError:
        return None
    if isinstance(data, dict) and "event" not in data and data.get("error"):
        return str(data["error"])[:200]
    return None


class TruthStream(threading.Thread):
    """Listens to one channel of Truth Social's streaming API and passes every new @realDonaldTrump
    post to deliver(status, channel) the moment it arrives. Needs the access token of a Truth Social
    account: the server refuses anonymous connections. Reconnects by itself; close() ends it."""

    RETRY_WAITS = (2, 5, 15, 30, 60, 120, 300)

    def __init__(self, channel, token, deliver, log=None, user_agent=None, url=STREAM_URL):
        super().__init__(name="stream-" + channel, daemon=True)
        self.channel = channel
        self.deliver = deliver
        self.log = log or (lambda message: None)
        self.connected = False
        self._halt = threading.Event()
        # The token goes where Truth Social's own web client puts it (the query) and in the standard header.
        self._url = url + "?" + urllib.parse.urlencode({"access_token": token, "stream": channel})
        self._headers = {
            "Authorization": "Bearer " + token,
            "Origin": "https://truthsocial.com",
            "User-Agent": user_agent or FALLBACK_USER_AGENT,  # Cloudflare turns away non-browser agents
        }

    def close(self):
        self._halt.set()

    def run(self):
        failures = 0
        while not self._halt.is_set():
            try:
                connection = ws_connect(self._url, self._headers, timeout=30)
            except WebSocketRefused as error:
                if error.status == 401:
                    self.log("Stream %s: Truth Social rejected the access token (HTTP 401); not streaming." % self.channel)
                    return
                if error.status in (400, 404, 422):
                    self.log("Stream %s: not offered by Truth Social (%s); not using it." % (self.channel, error))
                    return
                problem = "refused (%s)" % error
            except WebSocketError as error:
                problem = str(error)
            else:
                connected_at = time.monotonic()
                self.connected = True
                self.log("Stream %s: connected; new posts now arrive the moment they are made." % self.channel)
                problem, final = self._listen(connection)
                self.connected = False
                if final:
                    self.log("Stream %s: %s; not using it." % (self.channel, problem))
                    return
                if self._halt.is_set():
                    return
                if time.monotonic() - connected_at >= 60:  # it worked for a while: reconnect quickly;
                    failures = 0  # one that drops straight away keeps backing off instead
            wait = self.RETRY_WAITS[min(failures, len(self.RETRY_WAITS) - 1)]
            failures += 1
            self.log("Stream %s: %s; reconnecting in %d s." % (self.channel, problem, wait))
            self._halt.wait(wait)

    def _listen(self, connection):
        """Read until the connection ends -> (what happened, whether retrying is pointless)."""
        last_ping = time.monotonic()
        try:
            while not self._halt.is_set():
                message = connection.recv(timeout=1.0)
                now = time.monotonic()
                if message is None:
                    if now - connection.last_seen > STREAM_SILENCE:
                        return "nothing received for %d s" % STREAM_SILENCE, False
                    if now - last_ping > 30:  # keeps the line open and proves the server is still there
                        last_ping = now
                        try:
                            connection.ping()
                        except OSError as error:
                            return "connection lost (%s)" % error, False
                    continue
                if not isinstance(message, str):
                    continue
                status = stream_status(message)
                if status is not None:
                    try:
                        self.deliver(status, self.channel)
                    except Exception as error:  # the regular poll will report this post instead
                        self.log("Stream %s: could not handle post %s (%s: %s)." % (
                            self.channel, status.get("id"), type(error).__name__, error))
                    continue
                refusal = _stream_error(message)
                if refusal is not None:
                    return "refused by Truth Social (%s)" % refusal, True
            return "stopped", False
        except WebSocketError as error:
            return str(error), False
        finally:
            connection.close()


def _start_stream(channel, token, deliver, log, user_agent):
    stream = TruthStream(channel, token, deliver, log=log, user_agent=user_agent)
    stream.start()
    return stream


class FeedServer:
    """A small websocket server for other programs: every connected client is sent each reported
    post as one JSON text message, the moment it is reported. Clients only listen."""

    MAX_CLIENTS = 64
    _END = object()

    def __init__(self, host, port, log=None):
        self.log = log or (lambda message: None)
        try:
            self.sock = socket.create_server((host, port))
        except OSError as error:
            raise ScrapeError("cannot serve the feed on %s:%s (%s)" % (host, port, error)) from None
        self.sock.settimeout(1.0)
        self.address = self.sock.getsockname()[:2]
        self._clients = {}  # WebSocket -> queue of messages waiting to be sent to it
        self._lock = threading.Lock()
        self._closed = False
        threading.Thread(target=self._accept, name="feed-accept", daemon=True).start()

    def clients(self):
        with self._lock:
            return len(self._clients)

    def publish(self, text):
        """Queue a message for every client; never blocks. A client that has stopped reading is dropped."""
        with self._lock:
            targets = list(self._clients.items())
        for connection, outbox in targets:
            try:
                outbox.put_nowait(text)
            except queue.Full:
                self._drop(connection)

    def close(self):
        self._closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        with self._lock:
            connections = list(self._clients)
        for connection in connections:
            self._drop(connection)

    def _drop(self, connection):
        with self._lock:
            outbox = self._clients.pop(connection, None)
        if outbox is not None:
            try:
                outbox.put_nowait(self._END)
            except queue.Full:
                pass
        for end in (lambda: connection.sock.shutdown(socket.SHUT_RDWR), connection.sock.close):
            try:
                end()  # shutdown first: it wakes the thread that is waiting to read from this client
            except OSError:
                pass

    def _accept(self):
        while not self._closed:
            try:
                sock, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), name="feed-client", daemon=True).start()

    def _serve(self, sock):
        connection = None
        try:
            sock.settimeout(10)
            _, headers, rest = _read_http_head(sock)
            key = headers.get("sec-websocket-key")
            if "websocket" not in headers.get("upgrade", "").lower() or not key or self.clients() >= self.MAX_CLIENTS:
                body = b"This is a websocket feed of new @realDonaldTrump posts; connect with a websocket client.\n"
                sock.sendall(b"HTTP/1.1 426 Upgrade Required\r\nUpgrade: websocket\r\nConnection: close\r\n"
                             b"Content-Type: text/plain\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
                return
            connection = WebSocket(sock, client=False, leftover=rest)
            outbox = queue.Queue(maxsize=1000)
            with self._lock:  # registered before the handshake is answered: nothing published after that is missed
                self._clients[connection] = outbox
            sock.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Accept: %s\r\n\r\n" % _ws_accept(key)).encode("ascii"))
            threading.Thread(target=self._write, args=(connection, outbox), name="feed-writer", daemon=True).start()
            while not self._closed:
                if connection.recv(timeout=30) is None:  # quiet for a while: check the client is still there
                    if time.monotonic() - connection.last_seen > 90:
                        return
                    outbox.put_nowait(None)
        except (OSError, WebSocketError, ValueError, queue.Full):
            pass
        finally:
            if connection is not None:
                self._drop(connection)
            try:
                sock.close()
            except OSError:
                pass

    def _write(self, connection, outbox):
        try:
            while True:
                item = outbox.get()
                if item is self._END:
                    return
                if item is None:
                    connection.ping()
                else:
                    connection.send(item)
        except OSError:
            self._drop(connection)


# --------------------------------------------------------------------------
# Post text
# --------------------------------------------------------------------------

_BLOCK_TAGS = frozenset("p div blockquote ul ol li h1 h2 h3 h4 h5 h6 pre".split())
_VOID_TAGS = frozenset("br img hr input meta link wbr".split())
# Invisible characters that only get in the way of matching (ZWJ/ZWNJ are kept: emoji need them).
_INVISIBLE_RE = re.compile("[​⁠﻿­‎‏‪-‮⁦-⁩]")
_SPACE_RE = re.compile(r"[^\S\n]+")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            if tag not in _VOID_TAGS:
                self.skip_depth += 1
            return
        classes = (dict(attrs).get("class") or "").split()
        if tag == "span" and "quote-inline" in classes:
            # Truth Social's inline "RT: <link>" stub for a quoted post; the quote itself is stored separately.
            self.skip_depth = 1
        elif tag == "br":
            self.out.append("\n")
        elif tag in _BLOCK_TAGS:
            self.out.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        if not self.skip_depth and tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag not in _VOID_TAGS:
                self.skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self.out.append("\n\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(data)


def clean_text(text):
    """Normalise plain text: NFC, no invisible junk, single spaces, at most one blank line."""
    text = text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")  # drop lone surrogates
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(markup):
    """Convert a post's HTML body to plain text, keeping paragraph and line breaks."""
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return clean_text("".join(parser.out))


def parse_timestamp(value):
    """ISO 8601 timestamp from the API -> seconds since the epoch."""
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def normalize_status(status):
    """Flatten one API status object into a database row (dict)."""
    reblog = status.get("reblog") or None
    shown = reblog or status  # for a retruth, the text on the timeline is the original post's
    quote = shown.get("quote") or None
    card = shown.get("card") or None
    media = []
    for source in (shown, quote or {}):  # a quoted post's pictures/videos show in the post too
        for item in source.get("media_attachments") or []:
            url = item.get("url") or item.get("remote_url") or item.get("preview_url")
            if isinstance(url, str) and url.startswith(("https://", "http://")) and url not in media:
                media.append(url)
    post_id = int(status["id"])
    url = status.get("url")
    if not (isinstance(url, str) and url.startswith("https://")):
        url = "https://truthsocial.com/@%s/%d" % (ACCOUNT_HANDLE, post_id)
    return {
        "id": post_id,
        "created_at": status["created_at"],
        "created_ts": parse_timestamp(status["created_at"]),
        "url": url,
        "kind": "retruth" if reblog else "post",
        "author": ((reblog.get("account") or {}).get("acct") or None) if reblog else None,
        "text": html_to_text(shown.get("content") or ""),
        "quote_author": ((quote.get("account") or {}).get("acct") or None) if quote else None,
        "quote_text": html_to_text(quote.get("content") or "") if quote else None,
        "link_title": clean_text(html.unescape(card.get("title") or "")) or None if card else None,
        "link_url": (card.get("url") or None) if card else None,
        "media": json.dumps(media),
        "replies": int(status.get("replies_count") or 0),
        "retruths": int(status.get("reblogs_count") or 0),
        "likes": int(status.get("favourites_count") or 0),
    }


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    url          TEXT NOT NULL,
    kind         TEXT NOT NULL,
    author       TEXT,
    text         TEXT NOT NULL,
    quote_author TEXT,
    quote_text   TEXT,
    link_title   TEXT,
    link_url     TEXT,
    media        TEXT NOT NULL,
    replies      INTEGER NOT NULL,
    retruths     INTEGER NOT NULL,
    likes        INTEGER NOT NULL,
    fetched_at   REAL NOT NULL,
    raw          BLOB              -- zlib-compressed API object; NULL in downloaded snapshots
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_ROW_COLUMNS = (
    "id created_at created_ts url kind author text quote_author quote_text "
    "link_title link_url media replies retruths likes"
).split()


class Store:
    """The SQLite database. One instance per thread."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=60)
        self.db.executescript(_SCHEMA)

    def close(self):
        self.db.close()

    def get_meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, values):
        for key, value in values.items():
            if value is None:
                self.db.execute("DELETE FROM meta WHERE key = ?", (key,))
            else:
                self.db.execute("REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    def set_meta(self, **values):
        with self.db:
            self._set_meta(values)

    def save_page(self, statuses, now=None, **meta):
        """Insert/refresh one page of API statuses and update meta, atomically. Returns how many are new."""
        now = time.time() if now is None else now
        new = 0
        with self.db:
            for status in statuses:
                row = normalize_status(status)
                if not self.db.execute("SELECT 1 FROM posts WHERE id = ?", (row["id"],)).fetchone():
                    new += 1
                raw = zlib.compress(json.dumps(status, separators=(",", ":")).encode("ascii"))
                self.db.execute(
                    "REPLACE INTO posts (%s, fetched_at, raw) VALUES (%s, ?, ?)"
                    % (", ".join(_ROW_COLUMNS), ", ".join("?" * len(_ROW_COLUMNS))),
                    [row[column] for column in _ROW_COLUMNS] + [now, raw],
                )
            self._set_meta(meta)
        return new

    def reparse(self):
        """Recompute every derived column from the stored API objects. Returns the number of posts redone."""
        columns = _ROW_COLUMNS[1:]
        rows = self.db.execute("SELECT id, raw FROM posts WHERE raw IS NOT NULL").fetchall()
        with self.db:
            for post_id, raw in rows:
                row = normalize_status(json.loads(zlib.decompress(raw)))
                self.db.execute(
                    "UPDATE posts SET %s WHERE id = ?" % ", ".join("%s = ?" % column for column in columns),
                    [row[column] for column in columns] + [post_id])
        return len(rows)

    def sync_state(self):
        top, bottom = self.get_meta("contiguous_top"), self.get_meta("contiguous_bottom")
        return {
            "top": int(top) if top else None,
            "bottom": int(bottom) if bottom else None,
            "done": self.get_meta("history_complete") == "1",
        }

    def stats(self):
        count, oldest, newest = self.db.execute(
            "SELECT COUNT(*), MIN(created_ts), MAX(created_ts) FROM posts"
        ).fetchone()
        retruths = self.db.execute("SELECT COUNT(*) FROM posts WHERE kind = 'retruth'").fetchone()[0]
        last_sync = self.get_meta("last_sync")
        expected = self.get_meta("account_posts")
        return {
            "posts": count,
            "retruths": retruths,
            "oldest": oldest,
            "newest": newest,
            "last_sync": float(last_sync) if last_sync else None,
            "history_complete": self.get_meta("history_complete") == "1",
            "account_posts": int(expected) if expected else None,
        }

    def load_posts(self):
        """All posts, newest first, ready for searching."""
        rows = self.db.execute("SELECT %s FROM posts ORDER BY id DESC" % ", ".join(_ROW_COLUMNS))
        return [Post(*row) for row in rows]

    def posts_between(self, after_id, upto_id):
        """Posts with after_id < id <= upto_id, oldest first."""
        rows = self.db.execute(
            "SELECT %s FROM posts WHERE id > ? AND id <= ? ORDER BY id" % ", ".join(_ROW_COLUMNS), (after_id, upto_id))
        return [Post(*row) for row in rows]


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------

def sync(store, fetch_page, *, backfill=False, refresh_window=REFRESH_WINDOW, max_pages=None, progress=None,
         should_stop=None, now=None):
    """Bring the database up to date.

    1. Head: read from the newest post down until reaching posts already stored
       (and past refresh_window seconds of age, so recent posts get fresh counts).
       An empty database starts with the newest page.
    2. Backfill, only when asked: continue below the oldest stored post until the
       first post ever.

    The database tracks one gap-free block of post ids [bottom, top]; a run that is
    interrupted never leaves a hole, the next run simply redoes the unfinished part.
    Returns a summary dict.
    """
    now = time.time() if now is None else now
    state = store.sync_state()
    summary = {"new": 0, "seen": 0, "pages": 0, "stopped": False, "history_complete": state["done"]}
    stop = should_stop or (lambda: False)

    def record(page, **meta):
        expected = (page[0].get("account") or {}).get("statuses_count")
        if isinstance(expected, int):
            meta["account_posts"] = expected
        summary["new"] += store.save_page(page, **meta)
        summary["seen"] += len(page)
        summary["pages"] += 1
        if progress:
            progress(summary, page)

    def ids_of(page, max_id):
        ids = sorted(int(status["id"]) for status in page)
        if max_id is not None and ids[-1] >= max_id:
            raise ScrapeError("Truth Social ignored the paging cursor (got post %d at or above %d)" % (ids[-1], max_id))
        return ids

    def out_of_budget():
        return max_pages is not None and summary["pages"] >= max_pages

    # ---- 1. head
    if state["top"] is None:  # nothing stored yet: the newest page starts the block
        page = fetch_page(None)
        if not page:
            raise ScrapeError("Truth Social returned no posts at all for @%s" % ACCOUNT_HANDLE)
        ids = ids_of(page, None)
        state["top"], state["bottom"] = ids[-1], ids[0]
        record(page, contiguous_top=state["top"], contiguous_bottom=state["bottom"])
    else:
        max_id, newest, reached = None, None, False
        while True:
            page = fetch_page(max_id)
            if not page:
                if max_id is None:
                    raise ScrapeError("Truth Social returned no posts at all for @%s" % ACCOUNT_HANDLE)
                break  # walked past the first post ever while refreshing
            ids = ids_of(page, max_id)
            newest = ids[-1] if newest is None else newest
            max_id = ids[0]
            reached = reached or max_id <= state["top"]
            if reached:  # this run's pages now join the stored block: extend it
                state["top"] = max(state["top"], newest)
                state["bottom"] = min(state["bottom"], max_id)
                record(page, contiguous_top=state["top"], contiguous_bottom=state["bottom"])
            else:
                record(page)
            settled = (refresh_window <= 0
                       or min(parse_timestamp(status["created_at"]) for status in page) < now - refresh_window)
            if reached and settled:
                break
            if stop() or out_of_budget():
                summary["stopped"] = True
                break

    # ---- 2. backfill
    if backfill and not state["done"] and not summary["stopped"]:
        while True:
            if stop() or out_of_budget():
                summary["stopped"] = True
                break
            page = fetch_page(state["bottom"])
            if not page:
                page = fetch_page(state["bottom"])  # ask twice before believing history has ended
                if not page:
                    state["done"] = True
                    store.set_meta(history_complete=1)
                    break
            ids = ids_of(page, state["bottom"])
            state["bottom"] = ids[0]
            record(page, contiguous_top=state["top"], contiguous_bottom=state["bottom"])

    summary["history_complete"] = state["done"]
    if not summary["stopped"]:
        store.set_meta(last_sync=time.time())
    return summary


def reset_sync_state(store):
    """Forget how far the scrape got (posts are kept) so the next sync re-reads the whole history."""
    store.set_meta(contiguous_top=None, contiguous_bottom=None, history_complete=None)


_BUSY_MESSAGE = "another update of this database is already running"


class UpdateLock:
    """Only one update per database at a time. Released by the OS even if the process is killed."""

    def __init__(self, db_path):
        self.path = Path(str(db_path) + ".lock")
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            raise UpdateBusy(_BUSY_MESSAGE) from None
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            self.handle.close()  # closing releases the lock
            self.handle = None


def write_snapshot(db_path, out_path):
    """Write a consistent, slim copy of the database (no raw API blobs) - safe while an update runs."""
    out_path = Path(out_path)
    temp = out_path.with_name("%s.%d.tmp" % (out_path.name, os.getpid()))
    columns = ", ".join(_ROW_COLUMNS) + ", fetched_at"
    source = sqlite3.connect(str(db_path), timeout=60)
    try:
        if temp.exists():
            temp.unlink()
        target = sqlite3.connect(str(temp))
        try:
            target.executescript(_SCHEMA)
            source.execute("BEGIN")  # one read transaction: posts and meta from the same moment
            target.executemany(
                "INSERT INTO posts (%s) VALUES (%s)" % (columns, ", ".join("?" * (len(_ROW_COLUMNS) + 1))),
                source.execute("SELECT %s FROM posts" % columns))
            target.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", source.execute("SELECT key, value FROM meta"))
            source.execute("COMMIT")
            target.commit()
            count = target.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        finally:
            target.close()
        os.replace(temp, out_path)
        return count
    finally:
        source.close()
        if temp.exists():
            temp.unlink()


# ---- scraping on another machine ------------------------------------------

def _load_config():
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ScrapeError("cannot read %s: %s" % (CONFIG_PATH, error)) from None
    return config if isinstance(config, dict) else {}


def load_token():
    """The Truth Social access token for the streaming websocket: $TRUTHSOCIAL_TOKEN, or "token" in
    config.json. None when there is none, in which case new posts are found by polling alone."""
    token = os.environ.get("TRUTHSOCIAL_TOKEN") or _load_config().get("token")
    if not token:
        return None
    if not isinstance(token, str) or not re.fullmatch(r"[\x21-\x7e]+", token.strip()):
        raise ScrapeError("the Truth Social access token ($TRUTHSOCIAL_TOKEN or \"token\" in %s) is not a valid token"
                          % CONFIG_PATH)
    return token.strip()


def load_remote():
    """The "remote" entry of config.json: the machine that does the scraping, or None to scrape here.

    {"remote": {"ssh": "host", "dir": "/path/to/trump-social-scraper", "python": "/usr/bin/python3", "wrap": "nice"}}
    """
    remote = _load_config().get("remote")
    if not remote:
        return None
    if not isinstance(remote, dict) or not all(isinstance(remote.get(key), str) and remote[key] for key in ("ssh", "dir")):
        raise ScrapeError('%s: "remote" needs "ssh" (host) and "dir" (folder of this script on that host)' % CONFIG_PATH)
    return {
        "ssh": remote["ssh"],
        "dir": remote["dir"].rstrip("/"),
        "python": remote.get("python") or "python3",
        "wrap": remote.get("wrap") or "",
    }


def _remote_command(remote, *args):
    words = [remote["wrap"]] if remote["wrap"] else []
    words += [shlex.quote(remote["python"]), "-u", "trump_scraper.py"] + [shlex.quote(str(arg)) for arg in args]
    return "cd %s && %s" % (shlex.quote(remote["dir"]), " ".join(words))


def _ssh(remote, command, log, should_stop=None):
    """Run a command on the remote machine, passing each line it prints to log(). Returns its exit code."""
    try:
        proc = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30",
             remote["ssh"], command],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except OSError as error:
        raise ScrapeError("cannot run ssh: %s" % error) from None

    def watch():
        while proc.poll() is None:
            if should_stop():
                proc.terminate()
                return
            time.sleep(0.5)

    if should_stop is not None:
        threading.Thread(target=watch, daemon=True).start()
    try:
        for line in proc.stdout:
            if line.strip():
                log(line.rstrip())
        return proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.stdout.close()


def pull_database(remote, db_path, log=print):
    """Download a consistent copy of the remote machine's database and swap it in. Returns its post count."""
    output = []
    if _ssh(remote, _remote_command(remote, "snapshot"), output.append) != 0:
        raise ScrapeError("could not snapshot the database on %s: %s" % (remote["ssh"], " ".join(output)[-300:]))
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    part = db_path.with_name(db_path.name + ".part")
    log("Downloading the database from %s ..." % remote["ssh"])
    try:
        result = subprocess.run(
            ["scp", "-q", "-C", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20",
             "%s:%s/data/%s" % (remote["ssh"], remote["dir"], SNAPSHOT_NAME), str(part)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except OSError as error:
        raise ScrapeError("cannot run scp: %s" % error) from None
    if result.returncode != 0:
        raise ScrapeError("downloading the database failed: %s" % result.stdout.strip()[-300:])
    try:
        check = sqlite3.connect(str(part))
        try:
            intact = check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            count = check.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        finally:
            check.close()
    except sqlite3.Error as error:
        raise ScrapeError("the downloaded database is damaged (%s); the old one was kept" % error) from None
    if not intact:
        raise ScrapeError("the downloaded database is damaged; the old one was kept")
    for _ in range(20):
        try:
            os.replace(part, db_path)
            return count
        except PermissionError:  # Windows: someone is reading the old file this instant
            time.sleep(0.5)
    raise ScrapeError("could not replace %s - is it open in another program?" % db_path)


def run_update(db_path, solver_url=None, *, backfill=False, full=False, quick=False, max_pages=None,
               delay=DEFAULT_INTERVAL, log=print, progress=None, should_stop=None, quiet=False):
    """Update the database at db_path once.

    Scrapes here through FlareSolverr and returns sync()'s summary - or, when config.json
    names a remote machine, has that machine scrape, downloads its database and returns None.

    backfill: also download older history.  full: re-read everything (implies backfill).
    quick: only look for new posts, do not refresh the counts of recent ones.
    quiet: leave out routine progress messages (failures are still raised).
    """
    remote = load_remote()
    backfill = backfill or full
    note = (lambda message: None) if quiet else log
    with UpdateLock(db_path):
        if remote is not None:
            flags = ["--delay", delay]
            if backfill:
                flags.append("--history")
            if full:
                flags.append("--full")
            if quick:
                flags.append("--quick")
            if max_pages is not None:
                flags += ["--max-pages", max_pages]
            tail = collections.deque(maxlen=3)

            def relay(line):
                if _BUSY_MESSAGE in line:
                    return  # the normal case while a watch runs there; explained below
                tail.append(line.strip())
                note("[%s] %s" % (remote["ssh"], line.strip()))

            code = _ssh(remote, _remote_command(remote, "update", *flags), relay, should_stop)
            if code == EXIT_BUSY:
                note("%s is already updating (a watch is running there); fetching what it has." % remote["ssh"])
            elif code != 0:
                raise ScrapeError("the update on %s did not finish (exit code %s): %s"
                                  % (remote["ssh"], code, " | ".join(tail) or "no output"))
            pull_database(remote, db_path, note)
            return None
        store = Store(db_path)
        try:
            if full:
                reset_sync_state(store)
            with FlareSolverr(solver_url, log=log) as solver:
                client = TruthSocial(solver, interval=delay, log=log)
                return sync(store, client.fetch_page, backfill=backfill,
                            refresh_window=0 if quick else REFRESH_WINDOW, max_pages=max_pages,
                            progress=progress, should_stop=should_stop)
        finally:
            store.close()


# ---- live watching --------------------------------------------------------

def _connect(solver_url, interval, log, sleep):
    """A running FlareSolverr with an open browser, and a paced Truth Social client on top of it."""
    solver = FlareSolverr(solver_url, log=log).__enter__()
    return solver, TruthSocial(solver, interval=interval, log=log, sleep=sleep)


def watch_interval(interval=None):
    """Seconds between polls of a watch: the given value (or the default for this setup), never too fast."""
    if interval is None:
        interval = REMOTE_WATCH_INTERVAL if load_remote() else WATCH_INTERVAL
    return max(MIN_WATCH_INTERVAL, float(interval))


def watch(db_path, solver_url=None, *, interval=None, on_new=None, on_poll=None, log=print, should_stop=None,
          retry_first=False, token=None, streams=DEFAULT_STREAMS, connect=_connect, start_stream=_start_stream,
          clock=time.monotonic, sleep=time.sleep):
    """Keep the database current until should_stop() says so, reporting every new post.

    on_new(posts, live, source) gets new posts, oldest first. source is "poll", or "stream:<channel>"
    for a post pushed by Truth Social's streaming websocket. live is False when the posts may have
    been made a while ago: on the first poll, and on the first one after a failure.
    on_poll(error) is called after every poll with None or the failure message.

    How the database is kept current is picked automatically, poll by poll:
      - config.json names a remote machine: ask it to update, then download its database;
      - otherwise scrape here through FlareSolverr - one request per poll, browser kept open;
      - if another process holds the update lock on this database, just follow what it stores.

    With a Truth Social access token (and when scraping here), the streaming websocket is listened
    to as well: a post arriving that way is stored and reported at once, on the stream's own
    thread; the polls go on underneath and pick up anything a stream missed.

    A failed poll is reported and retried, it does not end the watch - except the very first
    one (unless retry_first), which is raised: that is a setup problem the caller should see.
    Each post is reported once; only a report whose on_new itself failed is made again.
    """
    stop = should_stop or (lambda: False)
    remote = load_remote()
    interval = watch_interval(interval)
    reporting = threading.Lock()  # one report at a time: the poll loop and the stream threads share it
    state = {"cursor": None}  # every post up to this id has been reported (or predates the watch)
    pushed = set()  # ids above the cursor that a stream has already reported

    def deliver(status, channel):
        """Called on a stream's thread with a post it was just sent."""
        post_id = int(status["id"])
        with reporting:
            store = Store(db_path)
            try:
                store.save_page([status])
                posts = store.posts_between(post_id - 1, post_id)
            finally:
                store.close()
            if state["cursor"] is None or post_id <= state["cursor"] or post_id in pushed:
                return  # already reported
            if on_new:
                on_new(posts, True, "stream:" + channel)
            pushed.add(post_id)

    def nap(seconds):
        deadline = clock() + seconds
        while True:
            if stop():
                raise _Stopped()
            left = deadline - clock()
            if left <= 0:
                return
            sleep(min(0.5, left))

    def read_top():
        store = Store(db_path)
        try:
            return store.sync_state()["top"]
        finally:
            store.close()

    lock = UpdateLock(db_path)
    solver = client = None
    connected_at = 0.0
    following = False  # another process is updating this database for us
    state["cursor"] = read_top()
    caught_up = False
    failures = polls = 0
    listeners = []
    try:
        while not stop():
            started = clock()
            error = None
            polls += 1
            try:
                if remote is not None:
                    try:
                        run_update(db_path, solver_url, quick=True, log=log, should_stop=should_stop, quiet=True)
                    except UpdateBusy:
                        pass  # someone else here is downloading the same database right now
                else:
                    if lock.handle is None:
                        try:
                            lock.__enter__()
                            if following:
                                log("The other process has finished; scraping here from now on.")
                            following = False
                        except UpdateBusy:
                            if not following:
                                log("Another process is already updating this database; following what it stores.")
                            following = True
                    if lock.handle is not None:
                        if client is not None and clock() - connected_at > SESSION_LIFETIME:
                            solver.close()
                            solver = client = None
                        if client is None:
                            solver, client = connect(solver_url, interval, log, nap)
                            connected_at = clock()
                        store = Store(db_path)
                        try:
                            sync(store, client.fetch_page, refresh_window=0, should_stop=should_stop)
                        finally:
                            store.close()
                # Report what joined the stored block since the last poll.
                with reporting:
                    top, cursor = read_top(), state["cursor"]
                    if top is not None and cursor is None:
                        log("Watching from here on; the newest posts so far are stored.")
                    elif top is not None and top > cursor:
                        store = Store(db_path)
                        try:
                            posts = [post for post in store.posts_between(cursor, top) if post.id not in pushed]
                        finally:
                            store.close()
                        if posts and on_new:
                            on_new(posts, caught_up, "poll")
                    if top is not None:
                        state["cursor"] = top if cursor is None else max(cursor, top)
                        pushed.difference_update([post_id for post_id in pushed if post_id <= state["cursor"]])
                # The streams start once the first poll has shown where "new" begins.
                if token and not listeners and client is not None:
                    agent = getattr(solver, "user_agent", None)
                    listeners.extend(start_stream(channel, token, deliver, log, agent) for channel in streams)
            except _Stopped:
                break
            except Exception as exc:  # whatever went wrong, the next poll starts from scratch
                error = str(exc) if isinstance(exc, ScrapeError) else "%s: %s" % (type(exc).__name__, exc)
                if solver is not None:
                    solver.close()
                    solver = client = None
                if polls == 1 and not retry_first:
                    raise

            if error is None:
                caught_up, failures = True, 0
            else:
                caught_up, failures = False, failures + 1
                log("Could not check for new posts (%s); trying again." % error)
            if on_poll:
                on_poll(error)

            pause = max(interval, client.interval if client is not None else 0.0)
            if error is not None:
                pause = min(600.0, pause * 2 ** min(failures, 5))
            try:
                nap(pause - (clock() - started))
            except _Stopped:
                break
    finally:
        for listener in listeners:
            listener.close()
        if solver is not None:
            solver.close()
        lock.__exit__()


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

_FOLD_SPECIAL = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "ʼ": "'", "`": "'", "´": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "«": '"', "»": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
}


class _FoldTable(dict):
    """Lazy str.translate table. Every character maps to exactly ONE character, so
    positions in folded text are positions in the original text."""

    def __missing__(self, codepoint):
        char = chr(codepoint)
        folded = _FOLD_SPECIAL.get(char)
        if folded is None:
            if unicodedata.category(char) == "Zs":
                folded = " "
            else:
                base = [c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c)]
                folded = base[0] if len(base) == 1 else char
                lower = folded.lower()
                if len(lower) == 1:
                    folded = lower
        self[codepoint] = folded
        return folded


_FOLD_TABLE = _FoldTable()


def fold(text):
    """Lower-case, strip accents, and unify quote/dash/space variants - without changing length."""
    return text.translate(_FOLD_TABLE)


class QueryError(ValueError):
    """The search query cannot be understood."""


class Term:
    """One keyword or phrase, matched as whole words; * stands for any run of word characters."""

    def __init__(self, text):
        self.text = " ".join(fold(text).split())
        words = self.text.split()
        if not words:
            raise QueryError("empty search term")
        if "*" in self.text and not any(c.isalnum() for c in self.text):
            raise QueryError("a wildcard (*) needs at least one letter or digit next to it: %s" % text)
        body = r"\s+".join(r"\w*".join(re.escape(piece) for piece in word.split("*")) for word in words)
        self.regex = re.compile(self._left_edge(words[0][0]) + body + self._right_edge(words[-1][-1]))
        # Cheap pre-check: the longest literal chunk must be present before the regex is tried.
        self.literal = max((piece for word in words for piece in word.split("*")), key=len)

    @staticmethod
    def _left_edge(char):
        if char.isdigit():  # "100" must not match inside "2,100" or "3.100"
            return r"(?<![\w])(?<!\d[.,])"
        return r"(?<!\w)" if (char == "*" or char.isalnum() or char == "_") else ""

    @staticmethod
    def _right_edge(char):
        if char.isdigit():  # "$100" must not match "$100,000" or "$100.50"
            return r"(?![\w]|[.,]\d)"
        return r"(?!\w)" if (char == "*" or char.isalnum() or char == "_") else ""

    def found_in(self, folded):
        return self.literal in folded and self.regex.search(folded) is not None

    def spans(self, folded):
        if self.literal not in folded:
            return []
        return [match.span() for match in self.regex.finditer(folded) if match.end() > match.start()]


_QUERY_TOKEN_RE = re.compile(r'(-?)"([^"]*)"|(\S+)')


class Query:
    """A set of terms: posts must contain all of `include` (or any, with match_any) and none of `exclude`."""

    def __init__(self, include=(), exclude=(), match_any=False):
        self.include = [Term(text) for text in include]
        self.exclude = [Term(text) for text in exclude]
        self.match_any = match_any

    @classmethod
    def parse(cls, text, match_any=False):
        """Search-box syntax: words, "exact phrases", wild* cards, -excluded -"excluded phrase"."""
        include, exclude = [], []
        for match in _QUERY_TOKEN_RE.finditer(fold(text)):
            negated, phrase, bare = match.groups()
            if bare is not None:
                if bare.startswith("-") and len(bare) > 1:
                    negated, bare = "-", bare[1:]
                phrase = bare.strip('"')
            if phrase.strip():
                (exclude if negated else include).append(phrase)
        return cls(include, exclude, match_any)

    def describe(self):
        def show(term):
            return '"%s"' % term.text if " " in term.text else term.text

        parts = [(" OR " if self.match_any else " AND ").join(show(term) for term in self.include)]
        parts += ["NOT " + show(term) for term in self.exclude]
        return " ".join(part for part in parts if part) or "(all posts)"

    def matches(self, folded_parts):
        for term in self.exclude:
            if any(term.found_in(part) for part in folded_parts):
                return False
        if not self.include:
            return True
        test = any if self.match_any else all
        return test(any(term.found_in(part) for part in folded_parts) for term in self.include)

    def spans(self, folded):
        """Merged, sorted [start, end) ranges of everything in `folded` that the include terms match."""
        merged = []
        for start, end in sorted(span for term in self.include for span in term.spans(folded)):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged

    def segments(self, text, folded):
        """Split `text` into [(chunk, is_match), ...] for highlighting."""
        out, position = [], 0
        for start, end in self.spans(folded):
            if start > position:
                out.append((text[position:start], False))
            out.append((text[start:end], True))
            position = end
        if position < len(text):
            out.append((text[position:], False))
        return out


class Post:
    __slots__ = _ROW_COLUMNS + ["f_text", "f_quote", "f_link"]

    def __init__(self, *row):
        for name, value in zip(_ROW_COLUMNS, row):
            setattr(self, name, value)
        self.media = json.loads(self.media) if isinstance(self.media, str) else list(self.media or [])
        self.quote_text = self.quote_text or ""
        self.link_title = self.link_title or ""
        self.f_text = fold(self.text)
        self.f_quote = fold(self.quote_text)
        self.f_link = fold(self.link_title)

    def parts(self, links=False):
        """The folded texts a query is matched against."""
        return (self.f_text, self.f_quote, self.f_link) if links else (self.f_text, self.f_quote)


SORTS = ("newest", "oldest", "likes", "retruths", "replies")
KINDS = ("all", "original", "retruth")


def filter_posts(posts, *, since=None, until=None, kind="all"):
    """Posts with since <= time < until (epoch seconds) of the given kind, order preserved."""
    out = []
    for post in posts:
        if since is not None and post.created_ts < since:
            continue
        if until is not None and post.created_ts >= until:
            continue
        if kind == "original" and post.kind == "retruth":
            continue
        if kind == "retruth" and post.kind != "retruth":
            continue
        out.append(post)
    return out


def search(posts, query, *, since=None, until=None, kind="all", sort="newest", links=False):
    """`posts` must be newest-first (as Store.load_posts returns them)."""
    hits = [post for post in filter_posts(posts, since=since, until=until, kind=kind)
            if query.matches(post.parts(links))]
    if sort == "oldest":
        hits.reverse()
    elif sort in ("likes", "retruths", "replies"):
        hits.sort(key=lambda post: getattr(post, sort), reverse=True)  # stable: ties stay newest-first
    elif sort != "newest":
        raise QueryError("unknown sort order: %s" % sort)
    return hits


def variation_hints(posts, query, *, links=False, top=6):
    """For plain single-word terms, list longer words a trailing * would also match.

    Searching `tariff` does not match `tariffs`; this tells the user what `tariff*` would add.
    `posts` should already be filtered by date/kind. Returns [{term, wildcard, words: [(word, posts)], more}].
    """
    hints = []
    for term in query.include:
        if not re.fullmatch(r"\w+", term.text):
            continue
        longer = re.compile(r"(?<!\w)" + re.escape(term.text) + r"\w+")
        counts = collections.Counter()
        for post in posts:
            words = set()
            for part in post.parts(links):
                if term.text in part:
                    words.update(longer.findall(part))
            counts.update(words)
        if counts:
            hints.append({
                "term": term.text,
                "wildcard": term.text + "*",
                "words": counts.most_common(top),
                "more": max(0, len(counts) - top),
            })
    return hints


def parse_day(value, utc=False):
    """'YYYY-MM-DD' -> epoch seconds of that day's midnight (local time, or UTC)."""
    try:
        day = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError:
        raise QueryError("dates must look like 2025-01-20, not %r" % value) from None
    return day.replace(tzinfo=timezone.utc).timestamp() if utc else day.timestamp()


def day_range(since=None, until=None, utc=False):
    """Inclusive since/until dates -> (since_ts, until_ts) with until_ts exclusive."""
    since_ts = parse_day(since, utc) if since else None
    until_ts = None
    if until:
        day = datetime.strptime(time.strftime("%Y-%m-%d", time.gmtime(parse_day(until, True))), "%Y-%m-%d")
        next_day = day + timedelta(days=1)
        until_ts = next_day.replace(tzinfo=timezone.utc).timestamp() if utc else next_day.timestamp()
    if since_ts is not None and until_ts is not None and since_ts >= until_ts:
        raise QueryError("--since %s is after --until %s" % (since, until))
    return since_ts, until_ts


def format_time(timestamp, utc=False):
    if utc:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def format_age(seconds):
    seconds = max(0, int(seconds))
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return "%d min ago" % round(seconds / 60)
    if seconds < 129600:
        return "%d h ago" % round(seconds / 3600)
    return "%d days ago" % round(seconds / 86400)


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

EXPORT_FIELDS = (
    "id created_at_utc created_at type retruth_of text quote_of quote_text "
    "link_title link_url media likes retruths replies url"
).split()


def export_rows(posts, utc=False):
    for post in posts:
        yield {
            "id": str(post.id),
            "created_at_utc": post.created_at,
            "created_at": format_time(post.created_ts, utc),
            "type": post.kind,
            "retruth_of": post.author or "",
            "text": post.text,
            "quote_of": post.quote_author or "",
            "quote_text": post.quote_text,
            "link_title": post.link_title,
            "link_url": post.link_url or "",
            "media": " ".join(post.media),
            "likes": post.likes,
            "retruths": post.retruths,
            "replies": post.replies,
            "url": post.url,
        }


def export_posts(posts, path, utc=False):
    """Write posts to .csv (Excel-friendly UTF-8) or .json, chosen by file extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".json"):
        raise QueryError("--export needs a file name ending in .csv or .json")
    rows = list(export_rows(posts, utc))
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    else:
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def _enable_ansi():
    """True when stdout is a terminal that will render ANSI colours."""
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def _highlight(query, text, folded, color):
    if not color:
        return text
    return "".join("\x1b[1;7m%s\x1b[0m" % chunk if hit else chunk for chunk, hit in query.segments(text, folded))


def _print_post(index, post, query, color, utc, links):
    dim = ("\x1b[2m", "\x1b[0m") if color else ("", "")
    label = "retruth of @%s" % post.author if post.kind == "retruth" else "post"
    print("%s[%d] %s | %s | likes %s | retruths %s | replies %s%s" % (
        dim[0], index, format_time(post.created_ts, utc), label,
        format(post.likes, ","), format(post.retruths, ","), format(post.replies, ","), dim[1]))
    if post.text:
        print(_highlight(query, post.text, post.f_text, color))
    if post.quote_author or post.quote_text:
        print("  > quoting @%s: %s" % (
            post.quote_author or "?", _highlight(query, post.quote_text, post.f_quote, color) or "(no text)"))
    if post.link_title:
        title = _highlight(query, post.link_title, post.f_link, color) if links else post.link_title
        print("  > link: %s" % title)
    if post.media:
        print("  > media: %s" % " ".join(post.media))
    if not (post.text or post.quote_text or post.link_title or post.media):
        print("  (no text)")
    print("%s%s%s\n" % (dim[0], post.url, dim[1]))


def _freshness_line(stats):
    if not stats["posts"]:
        return "The database is empty - run:  python trump_scraper.py update"
    line = "%s posts stored, %s to %s" % (
        format(stats["posts"], ","), format_time(stats["oldest"])[:10], format_time(stats["newest"]))
    if stats["last_sync"]:
        line += "; last update %s" % format_age(time.time() - stats["last_sync"])
    if not stats["history_complete"]:
        line += "; older posts are not stored (update --history downloads them)"
    return line


def _progress_printer():
    tty = sys.stdout.isatty()

    def progress(summary, page):
        oldest = min(parse_timestamp(status["created_at"]) for status in page)
        line = "  page %d: %s posts read, %s new, back to %s" % (
            summary["pages"], format(summary["seen"], ","), format(summary["new"], ","), format_time(oldest)[:10])
        if tty:
            sys.stdout.write("\r" + line.ljust(78))
            sys.stdout.flush()
        else:
            print(line.strip(), flush=True)

    return progress, (lambda: print() if tty else None)


def cmd_update(args):
    progress, finish = _progress_printer()
    remote = load_remote()
    print("Scraping @%s from truthsocial.com %s ..." % (
        ACCOUNT_HANDLE, "on %s" % remote["ssh"] if remote else "through FlareSolverr"), flush=True)
    try:
        try:
            summary = run_update(
                args.db, args.flaresolverr, backfill=args.history, full=args.full, quick=args.quick,
                max_pages=args.max_pages, delay=args.delay, progress=progress,
                log=lambda message: print(message, flush=True))
        finally:
            finish()
    except KeyboardInterrupt:
        print("Interrupted. Everything read so far is saved; run update again to continue.", flush=True)
        return 130
    store = Store(args.db)
    stats = store.stats()
    store.close()
    if summary is not None:
        print("Done: %s new posts (%s read in %d requests)." % (
            format(summary["new"], ","), format(summary["seen"], ","), summary["pages"]))
        if summary["stopped"]:
            print("Stopped at the --max-pages limit; run update again to continue.")
    print(_freshness_line(stats), flush=True)
    return 0


def post_record(post, detected, live, source="poll"):
    """One post of the live feed as a JSON-ready dict (the --json / --jsonl / --serve message format)."""
    return {
        "id": str(post.id),
        "created_at": post.created_at,
        "detected_at": datetime.fromtimestamp(detected, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "delay_seconds": round(max(0.0, detected - post.created_ts), 3),
        "live": bool(live),
        "source": source,
        "type": post.kind,
        "retruth_of": post.author,
        "text": post.text,
        "quote_of": post.quote_author,
        "quote_text": post.quote_text or None,
        "link_title": post.link_title or None,
        "link_url": post.link_url,
        "media": post.media,
        "url": post.url,
    }


def cmd_watch(args):
    include = [term.strip().strip('"') for term in args.terms]
    query = Query([term for term in include if term], args.exclude or [], match_any=args.any)
    interval = watch_interval(args.interval)
    remote = load_remote()
    notes = sys.stderr if args.json else sys.stdout  # --json keeps stdout for the posts alone
    color = _enable_ansi() and not args.no_color and not args.json
    counter = [0]

    def log(message):
        print("[%s] %s" % (format_time(time.time(), args.utc), message), file=notes, flush=True)

    def on_new(posts, live, source):
        now = time.time()
        wanted = [post for post in filter_posts(posts, kind=args.type) if query.matches(post.parts(args.links))]
        records = [post_record(post, now, live, source) for post in wanted]
        lines = [json.dumps(record, ensure_ascii=False) for record in records]
        if feed is not None:  # first: programs listening on the websocket get it before anything else happens
            for line in lines:
                feed.publish(line)
        if args.jsonl and lines:
            path = Path(args.jsonl)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write("".join(line + "\n" for line in lines))
        for post, record, line in zip(wanted, records, lines):
            if args.json:
                print(line, flush=True)
                continue
            counter[0] += 1
            age = record["delay_seconds"]
            print("--- new post, %s ---" % (
                "seen %.1f s after it was posted" % age if live and age < 600
                else "posted %s" % format_age(age).replace("just now", "moments ago")))
            _print_post(counter[0], post, query, color, args.utc, args.links)
            sys.stdout.flush()

    token = None if (args.no_stream or remote) else load_token()
    streams = tuple(args.stream) if args.stream else DEFAULT_STREAMS
    feed = None
    if args.serve:
        host, _, port = args.serve.rpartition(":")
        try:
            feed = FeedServer(host or "127.0.0.1", int(port), log=log)
        except ValueError:
            raise ScrapeError("--serve needs a port number or host:port, not %r" % args.serve) from None
    try:
        wanted = "" if not (query.include or query.exclude) else ", reporting posts matching %s" % query.describe()
        log("Watching @%s on truthsocial.com %s, checking every %d s%s. Ctrl+C stops." % (
            ACCOUNT_HANDLE, "via %s" % remote["ssh"] if remote else "through FlareSolverr", interval, wanted))
        if feed is not None:
            log("Serving the feed to websocket clients at ws://%s:%d/" % feed.address)
        if token:
            log("Access token found: also listening to Truth Social's streaming websocket (%s)." % ", ".join(streams))
        elif not remote and not args.no_stream:
            log("No Truth Social access token is configured, so posts are found by polling and can be up to "
                "%d s late. With a token ($TRUTHSOCIAL_TOKEN or \"token\" in config.json) they arrive "
                "instantly over Truth Social's streaming websocket." % interval)
        try:
            watch(args.db, args.flaresolverr, interval=interval, on_new=on_new, log=log, token=token, streams=streams)
        except KeyboardInterrupt:
            log("Stopped.")
    finally:
        if feed is not None:
            feed.close()
    return 0


def cmd_snapshot(args):
    out = Path(args.out) if args.out else Path(args.db).with_name(SNAPSHOT_NAME)
    count = write_snapshot(args.db, out)
    print("%s posts -> %s" % (format(count, ","), out))
    return 0


def cmd_search(args):
    if args.update:
        code = cmd_update(argparse.Namespace(
            db=args.db, flaresolverr=args.flaresolverr, history=False, full=False, quick=False, max_pages=None,
            delay=DEFAULT_INTERVAL))
        if code:
            return code
        print()
    include = [term.strip().strip('"') for term in args.terms]
    query = Query([term for term in include if term], args.exclude or [], match_any=args.any)
    since, until = day_range(args.since, args.until, args.utc)
    store = Store(args.db)
    stats = store.stats()
    posts = store.load_posts()
    store.close()
    if not posts:
        print(_freshness_line(stats))
        return 1
    candidates = filter_posts(posts, since=since, until=until, kind=args.type)
    hits = search(posts, query, since=since, until=until, kind=args.type, sort=args.sort, links=args.links)
    color = _enable_ansi() and not args.no_color
    limit = args.limit if args.limit is not None else (0 if args.export else 20)
    shown = hits if limit <= 0 else hits[:limit]

    if args.export:
        count = export_posts(shown, args.export, args.utc)
        print("Wrote %s posts to %s" % (format(count, ","), Path(args.export).resolve()))
    else:
        for index, post in enumerate(shown, 1):
            _print_post(index, post, query, color, args.utc, args.links)

    filters = []
    if args.since or args.until:
        filters.append("%s to %s" % (args.since or "start", args.until or "now"))
    if args.type != "all":
        filters.append({"original": "his own posts only", "retruth": "retruths only"}[args.type])
    print("%s %s %s%s" % (
        format(len(hits), ","), "post matches" if len(hits) == 1 else "posts match", query.describe(),
        " [%s]" % ", ".join(filters) if filters else ""), end="")
    if len(shown) < len(hits):
        print(" - showing the first %d by %s (--limit 0 for all)" % (len(shown), args.sort))
    else:
        print()
    for hint in variation_hints(candidates, query, links=args.links):
        words = ", ".join("%s (%s)" % (word, format(count, ",")) for word, count in hint["words"])
        more = " and %d more" % hint["more"] if hint["more"] else ""
        print('Note: "%s" matches that exact word only. %s would also match: %s%s' % (
            hint["term"], hint["wildcard"], words, more))
    print(_freshness_line(stats) + ("" if args.utc else "; times are local"))
    return 0


def cmd_status(args):
    store = Store(args.db)
    stats = store.stats()
    store.close()
    print("Database: %s" % Path(args.db).resolve())
    print(_freshness_line(stats))
    if stats["posts"]:
        print("%s are retruths, %s are his own posts." % (
            format(stats["retruths"], ","), format(stats["posts"] - stats["retruths"], ",")))
        if stats["account_posts"] is not None:
            print("Truth Social's own post counter for the account: %s." % format(stats["account_posts"], ","))
    remote = load_remote()
    if remote:
        print("Scraping runs on: %s:%s (config.json)" % (remote["ssh"], remote["dir"]))
    else:
        command = find_flaresolverr_command()
        print("FlareSolverr: %s" % (" ".join(command) if command else "none installed in %s" % (APP_DIR / "flaresolverr")))
    return 0


# --------------------------------------------------------------------------
# Web UI
# --------------------------------------------------------------------------

class App:
    """State shared by the web UI's request threads and its background watch thread."""

    def __init__(self, db_path, solver_url=None, interval=None):
        self.db_path = db_path
        self.solver_url = solver_url
        self.interval = interval
        self.lock = threading.Lock()
        self.posts = []
        self.stats = {}
        self.loaded_version = -1
        self.version = 0
        # live: a watch is running. checked: when it last looked for new posts successfully.
        self.sync = {"live": False, "checked": None, "error": None}
        self.stop_event = threading.Event()

    def snapshot(self):
        """(posts, stats), reloaded from disk whenever the watch has brought in something new."""
        with self.lock:
            if self.loaded_version != self.version:
                version = self.version
                store = Store(self.db_path)
                try:
                    self.posts, self.stats = store.load_posts(), store.stats()
                finally:
                    store.close()
                self.loaded_version = version
            return self.posts, self.stats

    def start_watch(self):
        with self.lock:
            if self.sync["live"]:
                return False
            self.sync = {"live": True, "checked": None, "error": None}
            self.stop_event.clear()
        threading.Thread(target=self._watch_thread, name="watch", daemon=True).start()
        return True

    def _watch_thread(self):
        def on_poll(error):
            with self.lock:
                if error is None:
                    self.version += 1  # re-read the database: new posts, or at least fresher counts
                    self.sync.update(checked=time.time(), error=None)
                else:
                    self.sync["error"] = error

        error = None
        try:
            watch(self.db_path, self.solver_url, interval=self.interval, on_poll=on_poll, token=load_token(),
                  log=lambda message: None, should_stop=self.stop_event.is_set, retry_first=True)
        except Exception as exc:  # keep the UI alive whatever happens in the scraper
            error = "%s: %s" % (type(exc).__name__, exc)
        with self.lock:
            self.version += 1
            self.sync["live"] = False
            if error is not None:
                self.sync["error"] = error

    def status(self):
        _, stats = self.snapshot()
        with self.lock:
            return dict(stats, sync=dict(self.sync), version=self.version, now=time.time())

    def search(self, params):
        def one(name, default=""):
            return (params.get(name) or [default])[0]

        try:
            sort, kind = one("sort", "newest"), one("type", "all")
            if sort not in SORTS or kind not in KINDS:
                raise QueryError("unknown sort or type")
            links = one("links") == "1"
            query = Query.parse(one("q"), match_any=one("any") == "1")
            since, until = day_range(one("since") or None, one("until") or None)
            offset, limit = max(0, int(one("offset", "0"))), min(200, max(1, int(one("limit", "50"))))
        except (QueryError, ValueError) as error:
            return {"error": str(error)}
        posts, stats = self.snapshot()
        candidates = filter_posts(posts, since=since, until=until, kind=kind)
        hits = search(posts, query, since=since, until=until, kind=kind, sort=sort, links=links)
        results = []
        for post in hits[offset:offset + limit]:
            results.append({
                "id": str(post.id),
                "time": post.created_ts * 1000,
                "url": post.url,
                "kind": post.kind,
                "author": post.author,
                "text": query.segments(post.text, post.f_text),
                "quote_author": post.quote_author,
                "quote": query.segments(post.quote_text, post.f_quote),
                "link_title": (query.segments(post.link_title, post.f_link) if links
                               else ([(post.link_title, False)] if post.link_title else [])),
                "link_url": post.link_url,
                "media": post.media,
                "likes": post.likes,
                "retruths": post.retruths,
                "replies": post.replies,
            })
        return {
            "total": len(hits),
            "offset": offset,
            "results": results,
            "description": query.describe(),
            "hints": variation_hints(candidates, query, links=links) if offset == 0 else [],
        }


class Handler(BaseHTTPRequestHandler):
    app = None  # set by cmd_ui
    server_version = "TrumpScraper"

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload).encode("ascii"), "application/json")

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif url.path == "/api/search":
            self._json(self.app.search(urllib.parse.parse_qs(url.query)))
        elif url.path == "/api/status":
            self._json(self.app.status())
        else:
            self._json({"error": "not found"}, 404)

def cmd_ui(args):
    app = App(args.db, args.flaresolverr, args.interval)
    Handler.app = app
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        print("Cannot listen on port %d (%s). Try: python trump_scraper.py ui --port %d" % (
            args.port, error, args.port + 1))
        return 1
    address = "http://127.0.0.1:%d/" % args.port
    _, stats = app.snapshot()
    print(_freshness_line(stats))
    if not args.no_update:
        print("Watching Truth Social for new posts in the background (every %d s) ..." % watch_interval(args.interval))
        app.start_watch()
    print("Search page: %s   (Ctrl+C to stop)" % address, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [address]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_event.set()
        server.server_close()
        deadline = time.monotonic() + 45
        while app.sync["live"] and time.monotonic() < deadline:  # let the scraper shut its browser
            time.sleep(0.5)
    return 0


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trump Truth Social search</title>
<style>
:root {
  --bg: #f4f2ec; --panel: #ffffff; --ink: #1c1d21; --muted: #646872; --line: #dedbd2;
  --accent: #a3271f; --accent-ink: #ffffff; --mark: #ffe17a; --mark-ink: #1c1d21; --chip: #ece9e0;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #121316; --panel: #1b1d21; --ink: #e9e9ec; --muted: #9a9ea9; --line: #2d3037;
    --accent: #ff8f84; --accent-ink: #1b1d21; --mark: #806000; --mark-ink: #ffffff; --chip: #26292f;
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 28px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
#status { color: var(--muted); font-size: 13px; margin: 0 0 18px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
#status.warn span { color: var(--accent); }
button, select, input { font: inherit; color: inherit; }
button { background: var(--chip); border: 1px solid var(--line); border-radius: 6px; padding: 3px 10px; cursor: pointer; }
button:disabled { opacity: .55; cursor: default; }
#q { width: 100%; padding: 12px 14px; font-size: 18px; border: 1px solid var(--line); border-radius: 10px;
  background: var(--panel); outline-offset: 2px; }
#q:focus { outline: 2px solid var(--accent); }
.controls { display: flex; flex-wrap: wrap; gap: 8px 14px; margin: 12px 0 6px; font-size: 14px; color: var(--muted); align-items: center; }
.controls label { display: inline-flex; gap: 6px; align-items: center; }
.controls select, .controls input[type=date] { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 3px 6px; }
.help { font-size: 13px; color: var(--muted); margin: 0 0 18px; }
.help code { background: var(--chip); padding: 1px 5px; border-radius: 4px; font-size: 12.5px; }
#summary { font-weight: 600; margin: 18px 0 6px; }
#summary.error { color: var(--accent); }
.hint { font-size: 14px; color: var(--muted); margin: 4px 0; }
.hint button { margin-left: 4px; }
article { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin: 12px 0; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 13px; color: var(--muted); margin-bottom: 6px; font-variant-numeric: tabular-nums; }
.meta .tag { background: var(--chip); border-radius: 4px; padding: 0 6px; color: var(--ink); }
.text { white-space: pre-wrap; overflow-wrap: anywhere; }
.quote { white-space: pre-wrap; overflow-wrap: anywhere; border-left: 3px solid var(--line); margin: 10px 0 0; padding: 2px 0 2px 12px; color: var(--muted); }
.quote b { color: var(--ink); font-weight: 600; }
.extra { font-size: 14px; margin-top: 8px; overflow-wrap: anywhere; color: var(--muted); }
.empty { color: var(--muted); font-style: italic; }
mark { background: var(--mark); color: var(--mark-ink); border-radius: 3px; padding: 0 1px; }
a { color: var(--accent); }
#more { display: block; margin: 18px auto; padding: 8px 22px; font-size: 15px; }
</style>
</head>
<body>
<main>
  <h1>Trump Truth Social search</h1>
  <p id="status"><span id="status-text">Loading ...</span><button id="fresh" type="button" hidden>New posts - show them</button></p>
  <input id="q" type="search" placeholder="Search keywords, e.g. tariff* china" autocomplete="off" autofocus>
  <div class="controls">
    <label>Match <select id="any"><option value="0">all words</option><option value="1">any word</option></select></label>
    <label>Show <select id="type"><option value="all">posts and retruths</option><option value="original">his own posts only</option><option value="retruth">retruths only</option></select></label>
    <label>Sort <select id="sort"><option value="newest">newest first</option><option value="oldest">oldest first</option><option value="likes">most liked</option><option value="retruths">most retruthed</option><option value="replies">most replies</option></select></label>
    <label>From <input id="since" type="date"></label>
    <label>to <input id="until" type="date"></label>
    <label><input id="links" type="checkbox"> also search link titles</label>
  </div>
  <p class="help">Whole words, any capitalisation. <code>tariff*</code> also finds tariffs, tariffed.
    <code>"fake news"</code> finds the exact phrase. <code>-biden</code> leaves out posts with that word.</p>
  <div id="summary"></div>
  <div id="hints"></div>
  <div id="results"></div>
  <button id="more" type="button" hidden>Show more</button>
</main>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
const FIELDS = ["q", "any", "type", "sort", "since", "until"];
const PAGE_SIZE = 50;
let shown = 0, total = 0, requestNumber = 0, lastSeen = null, timer = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function fill(node, segments) {
  for (const [chunk, hit] of segments) {
    node.appendChild(hit ? el("mark", "", chunk) : document.createTextNode(chunk));
  }
  return node;
}
function link(url, text) {
  const a = el("a", "", text);
  if (/^https?:\/\//i.test(url)) { a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
  return a;
}
function number(n) { return Number(n).toLocaleString("en-US"); }
function when(ms) {
  return new Date(ms).toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function ago(seconds) {
  if (seconds < 90) return "just now";
  if (seconds < 5400) return Math.round(seconds / 60) + " min ago";
  if (seconds < 129600) return Math.round(seconds / 3600) + " h ago";
  return Math.round(seconds / 86400) + " days ago";
}
function currentParams() {
  const params = new URLSearchParams();
  for (const id of FIELDS) { const value = $(id).value.trim(); if (value) params.set(id, value); }
  if ($("links").checked) params.set("links", "1");
  return params;
}
function renderPost(post) {
  const card = el("article");
  const meta = el("div", "meta");
  meta.appendChild(el("span", "", when(post.time)));
  if (post.kind === "retruth") meta.appendChild(el("span", "tag", "Retruth of @" + (post.author || "?")));
  meta.appendChild(el("span", "", number(post.likes) + " likes"));
  meta.appendChild(el("span", "", number(post.retruths) + " retruths"));
  meta.appendChild(el("span", "", number(post.replies) + " replies"));
  meta.appendChild(link(post.url, "Open on Truth Social"));
  card.appendChild(meta);
  if (post.text.length) card.appendChild(fill(el("div", "text"), post.text));
  if (post.quote.length || post.quote_author) {
    const quote = el("div", "quote");
    quote.appendChild(el("b", "", "Quoting @" + (post.quote_author || "?") + ": "));
    if (post.quote.length) fill(quote, post.quote);
    else quote.appendChild(el("span", "empty", "(no text)"));
    card.appendChild(quote);
  }
  if (post.link_title.length) {
    const extra = el("div", "extra");
    extra.appendChild(document.createTextNode("Link: "));
    const a = link(post.link_url || "", "");
    card.appendChild(extra).appendChild(fill(a, post.link_title));
  }
  if (post.media.length) {
    const extra = el("div", "extra", "Media: ");
    post.media.forEach((url, i) => {
      if (i) extra.appendChild(document.createTextNode(" · "));
      extra.appendChild(link(url, (/\.(mp4|mov|webm|m3u8)(\?|$)/i.test(url) ? "video " : "image ") + (i + 1)));
    });
    card.appendChild(extra);
  }
  if (!post.text.length && !post.quote.length && !post.quote_author && !post.link_title.length && !post.media.length) {
    card.appendChild(el("div", "empty", "(no text)"));
  }
  return card;
}
async function runSearch(append) {
  const mine = ++requestNumber;
  const params = currentParams();
  if (!append) history.replaceState(null, "", params.toString() ? "?" + params : location.pathname);
  params.set("offset", append ? shown : 0);
  params.set("limit", PAGE_SIZE);
  let data;
  try {
    data = await (await fetch("/api/search?" + params)).json();
  } catch (error) {
    data = { error: "The scraper is not answering - is it still running?" };
  }
  if (mine !== requestNumber) return;  // a newer search has started
  const summary = $("summary"), results = $("results"), hints = $("hints");
  if (data.error) {
    summary.className = "error"; summary.textContent = data.error;
    results.replaceChildren(); hints.replaceChildren(); $("more").hidden = true;
    return;
  }
  if (!append) { results.replaceChildren(); hints.replaceChildren(); shown = 0; $("fresh").hidden = true; }
  total = data.total;
  for (const post of data.results) results.appendChild(renderPost(post));
  shown += data.results.length;
  summary.className = "";
  summary.textContent = number(total) + (total === 1 ? " post matches " : " posts match ") + data.description;
  if (!append) {
    for (const hint of data.hints) {
      const row = el("div", "hint");
      const words = hint.words.map(([word, count]) => word + " (" + number(count) + ")").join(", ");
      row.appendChild(document.createTextNode("“" + hint.term + "” matches that exact word only. " +
        hint.wildcard + " would also match: " + words + (hint.more ? " and " + hint.more + " more" : "") + "."));
      const use = el("button", "", "Use " + hint.wildcard);
      use.type = "button";
      use.addEventListener("click", () => {
        const escaped = hint.term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        $("q").value = $("q").value.replace(new RegExp("(^|[\\s\"-])" + escaped + "(?=$|[\\s\"])", "i"), "$1" + hint.wildcard);
        runSearch(false);
      });
      row.appendChild(use);
      hints.appendChild(row);
    }
  }
  $("more").hidden = shown >= total;
  $("more").textContent = "Show more (" + number(total - shown) + " left)";
}
async function refreshStatus() {
  let status;
  try { status = await (await fetch("/api/status")).json(); } catch (error) { return schedule(5000); }
  const sync = status.sync;
  let line;
  if (!status.posts) line = "No posts stored yet.";
  else {
    line = number(status.posts) + " posts, " + new Date(status.oldest * 1000).toLocaleDateString() + " to " + when(status.newest * 1000);
    if (!status.history_complete) line += " · older posts are not stored";
  }
  if (sync.live) line += sync.checked ? " · live, checked " + ago(status.now - sync.checked) : " · connecting ...";
  else if (status.last_sync) line += " · not updating, last update " + ago(status.now - status.last_sync);
  if (sync.error) line += " · Update failed: " + sync.error;
  $("status-text").textContent = line;
  $("status").className = sync.error ? "warn" : "";
  const seen = status.posts ? status.posts + ":" + status.newest : "";
  if (lastSeen !== null && seen !== lastSeen) {  // the watch brought in new posts
    if (window.scrollY < 300 && shown <= PAGE_SIZE) runSearch(false);
    else $("fresh").hidden = false;
  }
  lastSeen = seen;
  schedule(5000);
}
function schedule(ms) { clearTimeout(timer); timer = setTimeout(refreshStatus, ms); }

const initial = new URLSearchParams(location.search);
for (const id of FIELDS) if (initial.has(id)) $(id).value = initial.get(id);
$("links").checked = initial.get("links") === "1";
let typing = null;
$("q").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => runSearch(false), 250); });
$("q").addEventListener("keydown", (event) => { if (event.key === "Enter") { clearTimeout(typing); runSearch(false); } });
for (const id of ["any", "type", "sort", "since", "until", "links"]) $(id).addEventListener("change", () => runSearch(false));
$("more").addEventListener("click", () => runSearch(true));
$("fresh").addEventListener("click", () => { window.scrollTo(0, 0); runSearch(false); });
runSearch(false);
refreshStatus();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=str(DEFAULT_DB), help="database file (default: %(default)s)")
    common.add_argument("--flaresolverr", metavar="URL", default=None,
                        help="FlareSolverr address (default: $FLARESOLVERR_URL or %s)" % DEFAULT_FS_URL)

    parser = argparse.ArgumentParser(
        description="Scrape Donald Trump's Truth Social posts and search them by keyword.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python trump_scraper.py watch                               print every new post as it appears
  python trump_scraper.py watch "tariff*" china --any         only posts mentioning tariffs or China
  python trump_scraper.py watch --jsonl data/feed.jsonl       also append each new post to a file
  python trump_scraper.py update
  python trump_scraper.py search tariff
  python trump_scraper.py search "tariff*" china              both words; tariff* also finds tariffs
  python trump_scraper.py search "fake news" --since 2025-01-20
  python trump_scraper.py search iran israel --any --type original --sort likes
  python trump_scraper.py search biden --exclude sleepy --export biden.csv
  python trump_scraper.py ui""")
    commands = parser.add_subparsers(dest="command", required=True)

    def add_filters(command):
        command.add_argument("--any", action="store_true", help="match posts containing ANY of the keywords")
        command.add_argument("--exclude", action="append", metavar="WORD",
                             help="leave out posts containing WORD (repeatable)")
        command.add_argument("--type", choices=KINDS, default="all",
                             help="his own posts, retruths, or both (default: all)")
        command.add_argument("--links", action="store_true", help="also search the titles of linked articles")
        command.add_argument("--utc", action="store_true", help="show (and filter) times in UTC instead of local time")
        command.add_argument("--no-color", action="store_true", help="do not highlight matches")

    live = commands.add_parser(
        "watch", parents=[common], help="live: report every new post as it appears",
        description="Report new posts until stopped (Ctrl+C): store them and print each one. With a Truth Social "
                    "access token ($TRUTHSOCIAL_TOKEN, or \"token\" in config.json) posts are pushed by Truth "
                    "Social's streaming websocket the moment they are made; without one, and as a safety net "
                    "with one, the newest posts are re-read every few seconds. With keywords, only matching "
                    "posts are reported (all are stored); the keyword rules are those of `search`. Posts made "
                    "while no watch was running are reported first, marked with their age.")
    live.add_argument("terms", nargs="*", help="only report posts with these keywords or \"exact phrases\"")
    add_filters(live)
    live.add_argument("--interval", type=float, metavar="SEC",
                      help="seconds between checks (default: %d, or %d when scraping runs on a remote machine; "
                           "minimum %d)" % (WATCH_INTERVAL, REMOTE_WATCH_INTERVAL, MIN_WATCH_INTERVAL))
    live.add_argument("--jsonl", metavar="FILE", help="also append every reported post to FILE, one JSON object per line")
    live.add_argument("--json", action="store_true",
                      help="print the posts as JSON lines (messages go to stderr), for piping into another program")
    live.add_argument("--serve", metavar="[HOST:]PORT",
                      help="also push every reported post, as JSON, to websocket clients connected to this "
                           "address (host defaults to 127.0.0.1)")
    live.add_argument("--stream", action="append", metavar="CHANNEL",
                      help="channel of Truth Social's streaming websocket to listen to when an access token is "
                           "configured (repeatable; default: %s)" % ", ".join(DEFAULT_STREAMS))
    live.add_argument("--no-stream", action="store_true",
                      help="do not use Truth Social's streaming websocket even if an access token is configured")
    live.set_defaults(run=cmd_watch)

    update = commands.add_parser("update", parents=[common], help="fetch new posts once")
    update.add_argument("--history", action="store_true",
                        help="also download older posts, back to the first one (hours; can be interrupted and resumed)")
    update.add_argument("--full", action="store_true", help="re-read the entire history (refreshes every post)")
    update.add_argument("--quick", action="store_true",
                        help="only look for new posts; do not refresh the like counts of the last days' posts")
    update.add_argument("--max-pages", type=int, metavar="N", help="stop after N requests (20 posts each)")
    update.add_argument("--delay", type=float, default=DEFAULT_INTERVAL, metavar="SEC",
                        help="seconds between requests (default: %(default)s; Truth Social blocks faster scraping)")
    update.set_defaults(run=cmd_update)

    find = commands.add_parser(
        "search", parents=[common], help="search stored posts by keyword",
        description="Search stored posts. Keywords match whole words in any capitalisation; put * at the end of a "
                    "word to match its variations (tariff* = tariff, tariffs, tariffed); quote several words to "
                    "match an exact phrase. With no keywords, lists posts.")
    find.add_argument("terms", nargs="*", help="keywords or \"exact phrases\"; all must appear unless --any")
    add_filters(find)
    find.add_argument("--since", metavar="YYYY-MM-DD", help="only posts from this day on")
    find.add_argument("--until", metavar="YYYY-MM-DD", help="only posts up to and including this day")
    find.add_argument("--sort", choices=SORTS, default="newest", help="result order (default: newest)")
    find.add_argument("--limit", type=int, metavar="N", help="how many to show (default: 20; 0 = all)")
    find.add_argument("--export", metavar="FILE", help="write the matches to FILE.csv or FILE.json instead of the screen")
    find.add_argument("--update", action="store_true", help="fetch new posts first")
    find.set_defaults(run=cmd_search)

    ui = commands.add_parser("ui", parents=[common], help="open the search page in your browser; it stays up to date")
    ui.add_argument("--port", type=int, default=8765, help="local port (default: %(default)s)")
    ui.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    ui.add_argument("--no-update", action="store_true", help="do not watch for new posts; search what is stored")
    ui.add_argument("--interval", type=float, metavar="SEC", help="seconds between checks for new posts")
    ui.set_defaults(run=cmd_ui)

    status = commands.add_parser("status", parents=[common], help="show what is in the database")
    status.set_defaults(run=cmd_status)

    snapshot = commands.add_parser(
        "snapshot", parents=[common], help="write a consistent copy of the database (works during an update)")
    snapshot.add_argument("--out", metavar="FILE", help="where to write it (default: %s next to the database)" % SNAPSHOT_NAME)
    snapshot.set_defaults(run=cmd_snapshot)
    return parser


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:  # never crash on an emoji when output is redirected to a file or pipe
            if stream.isatty():
                stream.reconfigure(errors="replace")
            else:
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    # Being terminated or losing the ssh session must still shut the browser down cleanly.
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None and signal.getsignal(number) is not signal.SIG_IGN:
            signal.signal(number, _interrupt)
    args = build_parser().parse_args(argv)
    try:
        return args.run(args)
    except UpdateBusy as error:
        print("Error: %s" % error, file=sys.stderr)
        return EXIT_BUSY
    except (ScrapeError, QueryError) as error:
        print("Error: %s" % error, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
