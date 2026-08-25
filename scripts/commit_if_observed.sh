#!/usr/bin/env bash
# Commit the observation log and its derived artefacts, but only when the log
# actually grew.
#
# This lives in a script rather than inline in the workflow because the inline
# version has now been wrong twice: once committing on every run (the report
# embeds a timestamp, so it always differs), and once failing the whole job
# because `git add` on a path that does not exist is fatal under `bash -e` --
# and a missing observation log is the normal state until a live provider runs.
# Shell embedded in YAML cannot be tested; this can.
#
# Usage: commit_if_observed.sh <log-path> [extra paths to include...]

set -euo pipefail

LOG=${1:?usage: commit_if_observed.sh <log-path> [extra paths...]}
shift
EXTRA=("$@")

if [ ! -f "$LOG" ]; then
  echo "No observation log at ${LOG}: nothing has been collected, so there is nothing to commit."
  exit 0
fi

git add -- "$LOG"

if git diff --staged --quiet; then
  echo "Observation log unchanged; nothing to commit."
  git reset -q
  exit 0
fi

# Only worth carrying the derived files once the log itself has moved.
for path in ${EXTRA[@]+"${EXTRA[@]}"}; do
  if [ -e "$path" ]; then
    git add -- "$path"
  fi
done

git commit -q -m "award-watch: hourly observation $(date -u +%Y-%m-%dT%H:%MZ)"
echo "Committed new observations."
git push
