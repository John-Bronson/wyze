#!/usr/bin/env bash
# Report files that differ between this checkout and the Pi.
#
# The push deploy model means the Pi has no history: anything edited there is
# invisible until something overwrites it. That is how the refresh_token() fix
# in token_manager.py survived only on the Pi from 2025-08-30 to 2026-09-07.
# Run this before deploying.
#
# Exit 0 = in sync, 1 = drift found.
set -uo pipefail

HOST="${WYZE_PI_HOST:-rpi-zero}"
REMOTE_DIR="${WYZE_PI_DIR:-/home/bronson/wyze}"
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 2

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Only compare what we actually deploy: git-tracked files, minus Pi-owned ones.
mapfile -t files < <(git ls-files | grep -vE '^(\.env|button_config\.json)$')

drift=0
for f in "${files[@]}"; do
  if ! scp -q "$HOST:$REMOTE_DIR/$f" "$tmp/remote" 2>/dev/null; then
    printf '  MISSING ON PI  %s\n' "$f"; drift=1; continue
  fi
  if ! diff -q "$f" "$tmp/remote" >/dev/null 2>&1; then
    lt=$(date -r "$f" +%s)
    rt=$(ssh "$HOST" "stat -c %Y '$REMOTE_DIR/$f'" 2>/dev/null || echo 0)
    lm=$(date -d "@$lt" '+%Y-%m-%d %H:%M')
    rm_=$(date -d "@$rt" '+%Y-%m-%d %H:%M')
    # Only the Pi holding the NEWER copy is real drift: that is an edit made
    # there that a deploy would destroy. A newer local copy is just an
    # undeployed change, which is the normal state before deploying.
    if [ "$rt" -gt "$lt" ]; then
      printf '  PI IS NEWER    %s   (local %s | pi %s)\n' "$f" "$lm" "$rm_"
      drift=1
    else
      printf '  pending        %s   (local %s | pi %s)\n' "$f" "$lm" "$rm_"
    fi
  fi
done

if [ "$drift" -eq 0 ]; then
  echo "No Pi-side drift; safe to deploy."
else
  echo
  echo "Pi-side changes would be OVERWRITTEN by a deploy."
  echo "Inspect one with:  ssh $HOST 'cat $REMOTE_DIR/<file>' | diff <file> -"
fi
exit "$drift"
