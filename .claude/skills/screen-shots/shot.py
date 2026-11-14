"""Take pictures of the screen running against the mock backend, so a change to ui/ is looked at, not assumed.

    uv run --with playwright python .claude/skills/screen-shots/shot.py                 # the market in second place
    uv run --with playwright python .claude/skills/screen-shots/shot.py --market 1 --say "This is a great demo"
    uv run --with playwright python .claude/skills/screen-shots/shot.py --ask "will the fed cut rates" --wait 3
    uv run --with playwright python .claude/skills/screen-shots/shot.py --keys r --out /tmp/record.png
    uv run --with playwright python .claude/skills/screen-shots/shot.py --click 1H --click Sources
    uv run --with playwright python .claude/skills/screen-shots/shot.py --width 420 --height 860   # a phone

It starts the mock backend and the Vite dev server on free ports, opens the page in headless Chrome,
presses what it was told to, saves a PNG and stops both. It prints the path of the picture and any error
the page threw; an error makes it exit 1.

The browser is the Chrome already on the machine. Where there is none: `uv run --with playwright playwright
install chromium`, and pass `--browser chromium`.
"""
import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[3] / "ui"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url: str, seconds: float = 30) -> None:
    end = time.time() + seconds
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.3)
    raise SystemExit(f"{url} did not answer within {seconds:.0f}s")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--market", type=int, default=2, help="place in the market list, from 1 (the demo market)")
    p.add_argument("--say", help="type this sentence to the made-up market, as a judge would")
    p.add_argument("--ask", help="ask this in the question box (the mock's magic words reach error states)")
    p.add_argument("--keys", default="", help="keys to press afterwards, one after another, e.g. 'r' or 'w'")
    p.add_argument("--click", action="append", default=[], metavar="TEXT",
                   help="click the button, tab or link with exactly this text; may be given more than once")
    p.add_argument("--hover", help="put the pointer at 'x,y' before the picture, e.g. '640,480' over the chart")
    p.add_argument("--wait", type=float, default=2.5, help="seconds to let the screen settle before the picture")
    p.add_argument("--width", type=int, default=1440)
    p.add_argument("--height", type=int, default=860)
    p.add_argument("--quiet", action="store_true", help="no scripted live ticks from the mock (prices still drift)")
    p.add_argument("--out", default="/tmp/terminal-screen.png")
    p.add_argument("--browser", default="chrome", choices=["chrome", "chromium"])
    a = p.parse_args()

    if not (UI / "node_modules").exists():
        raise SystemExit("ui/node_modules is missing: run `npm ci` in ui/ first")
    mock_port, ui_port = free_port(), free_port()
    env = {**os.environ, "MOCK_PORT": str(mock_port), **({"MOCK_QUIET": "1"} if a.quiet else {})}
    log = open("/tmp/terminal-screen-server.log", "w")
    # its own process group, so the mock and Vite both stop with it
    server = subprocess.Popen(["node", "mock/dev.mjs", "--port", str(ui_port), "--strictPort"], cwd=UI, env=env,
                              stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    errors: list[str] = []
    try:
        wait_for(f"http://localhost:{mock_port}/markets")
        wait_for(f"http://localhost:{ui_port}/")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome" if a.browser == "chrome" else None, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": a.width, "height": a.height})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://localhost:{ui_port}/")
            page.wait_for_timeout(1500)
            page.keyboard.press(str(a.market))
            page.wait_for_timeout(1000)
            if a.say:
                page.get_by_placeholder("Or type what you would say").fill(a.say)
                page.keyboard.press("Enter")
            if a.ask:
                page.locator("#ask-input").fill(a.ask)
                page.keyboard.press("Enter")
            for key in a.keys:
                page.wait_for_timeout(300)
                page.keyboard.press(key)
            for text in a.click:
                page.wait_for_timeout(300)
                def named(name):
                    return page.get_by_role("button", name=name).or_(page.get_by_role("tab", name=name)).or_(
                        page.get_by_role("link", name=name))
                # the exact text first; then text that starts with it, for a tab that carries a count ("Sources 8")
                target = named(re.compile(f"^{re.escape(text)}$"))
                if target.count() == 0:
                    target = named(re.compile(rf"^{re.escape(text)}(?![A-Za-z])"))
                if target.count() == 0:
                    errors.append(f"nothing to click with the text {text!r}")
                    continue
                target.first.click()
            if a.hover:
                x, y = (float(v) for v in a.hover.split(","))
                page.mouse.move(x, y)
            page.wait_for_timeout(int(a.wait * 1000))
            page.screenshot(path=a.out)
            browser.close()
    finally:
        os.killpg(server.pid, signal.SIGTERM)
        server.wait(timeout=10)
    print(a.out)
    for e in errors:
        print("page error:", e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
