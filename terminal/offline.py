"""The offline replay demo: the real backend and the built screen, playing the bundled replays, with no key
and no network.

    uv run python -m terminal.offline            # then open http://127.0.0.1:18912/?presentation=1

Nothing is polled, searched or scored: no Gemini call, no Context.dev call, no venue call. The three replays
in replays/ are loaded into a store of its own in a temporary folder, so the store of a live terminal is
never touched, and it is thrown away on exit. The made-up market is listed but takes no sentences: there is
no scorer here, and none is imitated.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
UI = ROOT / "ui"


def build_screen() -> None:
    """Build the screen once, to be served from the address the backend is on."""
    if (UI / "dist" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("The screen is not built and npm was not found. Install Node.js, or build ui/ on another machine.")
    print("Building the screen (once)…", flush=True)
    env = {**os.environ, "VITE_API_URL": ""}  # empty: the screen talks to the address it came from
    if not (UI / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=UI, env=env, check=True)
    subprocess.run([npm, "run", "build"], cwd=UI, env=env, check=True)


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--host", default="127.0.0.1")
    args.add_argument("--port", type=int, default=18912, help="not the live terminal's 18911, so both can run")
    args.add_argument("--db", help="keep the demo store at this path instead of a temporary one")
    opts = args.parse_args()

    import uvicorn

    from terminal.api import REPLAYS, create_app

    build_screen()
    folder = None if opts.db else tempfile.mkdtemp(prefix="terminal-offline-")
    path = opts.db or str(Path(folder) / "demo.db")
    app = create_app(db_path=path, offline=True, key="", ui=UI / "dist", replays=REPLAYS)
    print(f"Offline replay demo: http://{opts.host}:{opts.port}/?presentation=1   (store: {path})", flush=True)
    try:
        uvicorn.run(app, host=opts.host, port=opts.port, log_level="warning")
    finally:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
