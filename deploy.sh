#!/usr/bin/env bash
# Push this checkout to the Pi and restart its services.
#
# PyCharm's SFTP auto-upload already copies files on save; this script is the
# "make it live" step, since uploading does not restart gunicorn. It re-syncs
# first so it is also correct when run standalone, from any terminal.
#
#   ./deploy.sh           sync + restart (refuses if the Pi has local edits)
#   ./deploy.sh --force   deploy anyway, overwriting Pi-side edits
set -euo pipefail

HOST="${WYZE_PI_HOST:-rpi-zero}"
REMOTE_DIR="${WYZE_PI_DIR:-/home/bronson/wyze}"
cd "$(dirname "${BASH_SOURCE[0]}")"

force=0
[ "${1:-}" = "--force" ] && force=1

if ! ./check-drift.sh; then
  if [ "$force" -eq 0 ]; then
    echo
    echo "Refusing to deploy. Fold the Pi's version into the repo first," \
         "or re-run with --force to overwrite it."
    exit 1
  fi
  echo ">> --force given, overwriting Pi-side changes"
fi

# .env holds the Pi's real credentials and button_config.json is written by the
# Flask UI. Both are Pi-owned state; never push them. No --delete, for the same
# reason: files that exist only on the Pi are intentional.
echo ">> syncing to $HOST:$REMOTE_DIR"
rsync -az --itemize-changes \
  --exclude '.git/' --exclude '.idea/' --exclude '.venv/' \
  --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude '.env' --exclude 'button_config.json' \
  --exclude '.tokens.json' --exclude 'logs/' \
  --exclude 'chat-*.txt' \
  ./ "$HOST:$REMOTE_DIR/"

echo ">> restarting services"
ssh "$HOST" 'sudo systemctl restart wyze-flask wyze-button'

# A crash-looping unit reads "active" between restarts, so a single is-active
# check is not enough: compare the restart counter across a settling window.
echo ">> health check"
before=$(ssh "$HOST" 'for u in wyze-flask wyze-button; do \
  systemctl show -p NRestarts --value $u; done' | paste -sd, - || true)
sleep 12
rc=0
for unit in wyze-flask wyze-button; do
  state=$(ssh "$HOST" "systemctl is-active $unit" || true)
  n=$(ssh "$HOST" "systemctl show -p NRestarts --value $unit" || true)
  printf '   %-12s %-12s restarts=%s\n' "$unit" "$state" "$n"
done
after=$(ssh "$HOST" 'for u in wyze-flask wyze-button; do \
  systemctl show -p NRestarts --value $u; done' | paste -sd, - || true)
if [ "$before" != "$after" ]; then
  echo "   !! a unit restarted during the check window - it is crash-looping"
  echo "   !! restart counts went [$before] -> [$after]"
  ssh "$HOST" 'sudo journalctl -u wyze-button -n 12 --no-pager' | tail -8
  rc=1
fi

code=$(ssh "$HOST" 'curl -s -m 20 -o /dev/null -w "%{http_code}" http://localhost/')
echo "   http://$HOST/  ->  HTTP $code"
echo ">> done"
exit "$rc"
