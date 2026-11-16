#!/usr/bin/env bash
# Lint the last 1000 non-merge commits of three public projects, first with
# the default rules and then with a config matching each project's own
# conventions. Usage: scripts/survey.sh [work_dir]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-/tmp/cmlint-survey}"
mkdir -p "$WORK"
lint() { PYTHONPATH="$ROOT" python3 -m cmlint log --repo "$1" -n 1000 --no-merges --summary || true; }

for slug in vitejs/vite conventional-changelog/commitlint pallets/flask; do
  name="${slug#*/}"
  dir="$WORK/$name.git"
  [ -d "$dir" ] || git clone -q --bare --filter=tree:0 --depth 1000 "https://github.com/$slug" "$dir"
  rm -f "$dir/.cmlint.toml"
  echo "## $slug at $(git -C "$dir" rev-parse --short=10 HEAD) ($(git -C "$dir" log -1 --format=%cs))"
  echo; echo "Default rules:"; echo '```'; lint "$dir"; echo '```'
  case "$name" in
    vite)       printf '%s\n' 'types = ["feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert", "release"]' 'header-max-length = 100' > "$dir/.cmlint.toml" ;;
    commitlint) printf '%s\n' "ignore-patterns = ['^v\\d+\\.\\d+\\.\\d+']" 'header-max-length = 100' > "$dir/.cmlint.toml" ;;
    *)          continue ;;
  esac
  echo; echo "Project config (\`.cmlint.toml\`):"; echo '```toml'; cat "$dir/.cmlint.toml"; echo '```'; echo '```'; lint "$dir"; echo '```'; echo
  rm -f "$dir/.cmlint.toml"
done
