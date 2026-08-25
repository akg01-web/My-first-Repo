#!/usr/bin/env bash
# Exercises scripts/commit_if_observed.sh against the three states the hourly
# poll actually encounters. Run: bash tests/test_commit_step.sh
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/commit_if_observed.sh"
FAILS=0

check() { # name, expected-substring, actual
  if printf '%s' "$3" | grep -qF "$2"; then echo "PASS $1"; else
    echo "FAIL $1: expected to find '$2' in:"; printf '%s\n' "$3" | sed 's/^/    /'
    FAILS=$((FAILS + 1))
  fi
}

sandbox() {
  d=$(mktemp -d)
  # A bare upstream, because the script pushes and a push with no remote fails
  # with git's exit code 128 -- which would mask the failures being tested for.
  git init -q --bare "$d.git"
  git -C "$d" init -q
  git -C "$d" remote add origin "$d.git" 2>/dev/null || true
  git -C "$d" config user.email t@example.com
  git -C "$d" config user.name Test
  mkdir -p "$d/data" "$d/docs"
  echo seed > "$d/docs/award-watch.md"
  git -C "$d" add -A >/dev/null; git -C "$d" commit -qm seed
  git -C "$d" push -q -u origin HEAD 2>/dev/null || true
  printf '%s' "$d"
}

# 1. No log at all -- the normal state before any live provider has run.
#    This is the case that failed three consecutive scheduled runs.
d=$(sandbox)
out=$(cd "$d" && bash "$SCRIPT" data/observations.csv docs/award-watch.md 2>&1); rc=$?
check "missing log exits 0" "nothing to commit" "$out"
[ "$rc" -eq 0 ] || { echo "FAIL missing log should exit 0, got $rc"; FAILS=$((FAILS + 1)); }

# 2. Log exists but is unchanged since the last commit.
d=$(sandbox)
echo "header" > "$d/data/observations.csv"
git -C "$d" add -A >/dev/null; git -C "$d" commit -qm "with log"
before=$(git -C "$d" rev-parse HEAD)
echo "changed" > "$d/docs/award-watch.md"   # report churns; log does not
out=$(cd "$d" && bash "$SCRIPT" data/observations.csv docs/award-watch.md 2>&1)
check "unchanged log makes no commit" "Observation log unchanged" "$out"
[ "$(git -C "$d" rev-parse HEAD)" = "$before" ] || { echo "FAIL committed despite unchanged log"; FAILS=$((FAILS + 1)); }
[ -z "$(git -C "$d" diff --staged --name-only)" ] || { echo "FAIL left files staged"; FAILS=$((FAILS + 1)); }

# 3. Log grew -- the derived report should ride along.
d=$(sandbox)
echo "header" > "$d/data/observations.csv"
git -C "$d" add -A >/dev/null; git -C "$d" commit -qm "with log"
before=$(git -C "$d" rev-parse HEAD)
echo "a new row" >> "$d/data/observations.csv"
echo "refreshed" > "$d/docs/award-watch.md"
out=$(cd "$d" && bash "$SCRIPT" data/observations.csv docs/award-watch.md 2>&1)
[ "$(git -C "$d" rev-parse HEAD)" != "$before" ] || { echo "FAIL did not commit a grown log"; FAILS=$((FAILS + 1)); }
files=$(git -C "$d" show --stat --name-only --format= HEAD)
check "grown log is committed" "data/observations.csv" "$files"
check "report rides along" "docs/award-watch.md" "$files"

# 4. A named extra path that does not exist must not be fatal.
d=$(sandbox)
echo "header" > "$d/data/observations.csv"
out=$(cd "$d" && bash "$SCRIPT" data/observations.csv docs/award-watch.md .awardwatch_state.json 2>&1); rc=$?
[ "$rc" -eq 0 ] || { echo "FAIL missing extra path should not be fatal, got $rc"; FAILS=$((FAILS + 1)); }
echo "PASS missing extra path is tolerated"

echo; echo "$FAILS failure(s)"
[ "$FAILS" -eq 0 ]
