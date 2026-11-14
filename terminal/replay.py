"""Replays: finished markets with what was posted in their last hours, each post scored as it would have
been live. scripts/make_replay.py builds them into replays/; here each becomes a market that nothing polls
or changes, and the screen plays it back by itself.
"""
import json
import logging
from pathlib import Path

from terminal import db as store

log = logging.getLogger(__name__)


def _keep(db, r: dict) -> None:
    store.add_market(db, id=r["id"], venue=r["venue"], venue_ref=None, title=r["title"], rules=r["rules"],
                     url=r["url"], poll_seconds=0,
                     replay={"start": r["start"], "end": r["end"], "outcome": r["outcome"]})
    store.add_history(db, r["id"], [tuple(p) for p in r["prices"]])
    for t in r["ticks"]:
        # prerecorded: found and scored when the replay was built, so it has no live discovery or scoring time
        store.add_tick(db, {**t, "market_id": r["id"], "test": False, "backfill": False, "hidden": False,
                            "dedupe_key": t["url"], "rule": t["rule"] and json.dumps(t["rule"]),
                            "provenance": "replay", "discovered_ts": None, "scored_ts": None})


def load(db, folder: Path) -> list[str]:
    """Make the store's replays the ones in the folder. Returns their ids; a file that cannot be read is skipped."""
    for id in store.replay_ids(db):
        store.delete_market(db, id)
    loaded = []
    for file in sorted(folder.glob("*.json")):
        try:
            r = json.loads(file.read_text())
            id = r["id"]
        except (KeyError, TypeError, ValueError) as e:
            log.warning("replay %s not loaded: %s: %s", file.name, type(e).__name__, e)
            continue
        try:
            _keep(db, r)
            loaded.append(id)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("replay %s not loaded: %s: %s", file.name, type(e).__name__, e)
            store.delete_market(db, id)  # no half-loaded market
    return loaded
