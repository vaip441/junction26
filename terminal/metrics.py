"""How fast the terminal is, measured: from the timestamps stored on live ticks and from the durations of
recent requests. A query over what is stored, not a metrics service.

Two stretches of a tick's life are reported:
- publication to discovery: from the time the publisher states to the moment the item reached us. Only for
  ticks whose publish time is known.
- discovery to scored: from that moment until the item had been scored and stored, ready for the tape.

Only live ticks on real markets count (see db.live_timings). With fewer than MIN_SAMPLES ticks the median and
p95 are None: a number from three ticks would be noise, and a zero would be a lie.
"""
import math
import time
from collections import deque

from terminal import db as store

MIN_SAMPLES = 5
WINDOW = 86400
PRICE_CHECK_SECONDS = 60  # how often the price loop asks the venues (poller.price_loop)
_recent: dict[str, deque] = {}  # kind of request -> durations in seconds of the latest ones, this process only


def timed(kind: str, seconds: float) -> None:
    """Note how long one outside request took, measured by the caller on a monotonic clock."""
    _recent.setdefault(kind, deque(maxlen=200)).append(seconds)


def summary(values: list[float]) -> dict:
    """{"n", "median", "p95"} in seconds; the two figures are None below MIN_SAMPLES. p95 is the nearest rank:
    the smallest sample that at least 95% of the samples do not exceed."""
    v = sorted(values)
    if len(v) < MIN_SAMPLES:
        return {"n": len(v), "median": None, "p95": None}
    mid = len(v) // 2
    median = v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
    return {"n": len(v), "median": median, "p95": v[math.ceil(0.95 * len(v)) - 1]}


def latency(db, now: float | None = None, window: float = WINDOW) -> dict:
    now = time.time() if now is None else now
    rows = store.live_timings(db, now - window)
    # a publisher's clock that runs ahead of ours would give a negative wait: such a tick says nothing here
    waited = [r["discovered_ts"] - r["published_ts"] for r in rows
              if r["published_ts"] is not None and r["discovered_ts"] >= r["published_ts"]]
    # stored hidden without the model being asked (trash), or scored as no news: either way not a scored call
    # on the tape, so only shown ticks say how long scoring takes
    scored = [r["scored_ts"] - r["discovered_ts"] for r in rows if r["scored_ts"] is not None and not r["hidden"]]
    return {"window_seconds": int(window), "min_samples": MIN_SAMPLES, "ticks": len(rows),
            "publication_to_discovery": summary(waited), "discovery_to_scored": summary(scored),
            # how long the latest outside requests took, since this process started
            "requests": {kind: summary(list(times)) for kind, times in sorted(_recent.items())},
            "price_check_seconds": PRICE_CHECK_SECONDS}
