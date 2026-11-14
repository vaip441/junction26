"""Delete every Context.dev monitor this store knows of, and forget the pages, so they stop costing credits.
Stop the terminal first, or it sets them up again on its next pass (unless PUBLIC_URL is unset).

    PYTHONPATH=. uv run --env-file .env python scripts/stop_monitors.py data/terminal.db
"""
import asyncio
import sys

from terminal import contextdev
from terminal import db as store


async def main(path: str) -> None:
    db = store.connect(path)
    for id, monitor in db.execute("SELECT id, monitor_id FROM pages").fetchall():
        if monitor is None or await contextdev.delete_monitor(monitor):
            db.execute("DELETE FROM pages WHERE id = ?", (id,))
        else:
            print(f"monitor {monitor} was not found on any key; its page is kept")
    print(db.execute("SELECT COUNT(*) FROM pages").fetchone()[0], "pages left")


asyncio.run(main(sys.argv[1]))
