#!/usr/bin/env bash
# Everything that must pass before a change is pushed: the backend's tests, the scraper's tests, and the
# screen's typecheck, build and lint. No network and no keys are needed. Run from anywhere in the repo.
#
#   .claude/skills/check-all/check.sh          all three
#   .claude/skills/check-all/check.sh backend  only the part named: backend, scraper or screen
set -u
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$root" || exit 2
want="${1:-all}"
failed=()

step() { # name, directory, command...
  local name="$1" dir="$2"; shift 2
  [ "$want" = all ] || [ "$want" = "$name" ] || return 0
  printf '\n== %s ==\n' "$name"
  if (cd "$dir" && "$@"); then printf 'ok: %s\n' "$name"; else failed+=("$name"); printf 'FAILED: %s\n' "$name"; fi
}

screen() {
  # a clean install only when the lock file changed since the last one, or nothing is installed yet
  if [ ! -d node_modules ] || [ package-lock.json -nt node_modules/.package-lock.json ]; then npm ci --silent || return 1; fi
  npm run --silent build && npm run --silent lint
}

step backend . uv run pytest -q
step scraper trump-social-scraper python3 -m unittest -q test_trump_scraper
step screen ui screen

printf '\n'
if [ ${#failed[@]} -gt 0 ]; then echo "FAILED: ${failed[*]}"; exit 1; fi
echo "all passed"
