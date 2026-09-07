# Wyze Device Controller

A Flask web app and a GPIO button daemon for controlling Wyze plugs and bulbs,
running on a Raspberry Pi Zero 2 W.

- **Web UI** — lists devices, toggles them, and manages the button group
- **GPIO button** — a physical button on pin 4 toggles a group of devices to a
  single shared state by majority vote
- **`/logs`** — application logs and token status in the browser

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in your Wyze credentials
```

`WYZE_KEY_ID` and `WYZE_API_KEY` are issued as a matched pair at
<https://developer-api-console.wyze.com> and must always be regenerated
together. See `.env.example`.

## Deploying to the Pi

```bash
./check-drift.sh    # what differs between here and the Pi
./deploy.sh         # sync, restart services, health check
```

`deploy.sh` refuses to run when the Pi holds a newer copy of a file, so an edit
made directly on the Pi cannot be silently overwritten. `--force` overrides it.

`.env`, `button_config.json`, `.tokens.json` and `logs/` are Pi-owned state and
are never pushed. First-time server setup is in `install.md`; finding the Pi on
the network is in `network-discovery.md`.

## Services on the Pi

| Unit | What it runs |
|---|---|
| `wyze-flask.service` | gunicorn behind nginx |
| `wyze-button.service` | `button.py`, the GPIO listener |

```bash
sudo systemctl status wyze-flask wyze-button
sudo journalctl -u wyze-button -f
tail -f ~/wyze/logs/button.log
```

---

# Memory tuning on a Pi Zero 2 W

The Pi Zero 2 W has 512MB, of which ~416MB is usable. A stock Raspberry Pi OS
Desktop install running this app used **272MB with 196MB swapped to the SD
card** — the app's own pages were being paged out, which is slow and wears the
card.

The changes below took it to **197MB used with zero swap**. Each is
independently reversible.

| | Before | After |
|---|---|---|
| Used | 272MB | **197MB** |
| Available | 144MB | **218MB** |
| Swap in use | 196MB | **0B** |

## Why the app is the biggest consumer

Most of the memory is not application code. `import wyze_sdk` alone costs about
35MB:

```
bare interpreter        7 MB
+ requests             24 MB
+ wyze_sdk             42 MB
+ flask                28 MB
```

`button.py` and the gunicorn worker each import it, so that cost is paid twice.
There is no trimming to do in this project's own code.

## 1. Boot to console instead of the desktop

The largest single win, and the one that eliminated swapping. Only do this if
the Pi is headless.

```bash
sudo systemctl set-default multi-user.target
sudo reboot
```

Reverse:

```bash
sudo systemctl set-default graphical.target
sudo reboot
```

## 2. Mask the audio stack

PipeWire and WirePlumber were ~32MB. They are **user** services, not system
ones, so no sudo — and they are socket-activated, so `mask` is required;
`disable` alone leaves the sockets able to start them again.

```bash
systemctl --user mask --now \
  pipewire.socket pipewire.service \
  pipewire-pulse.socket pipewire-pulse.service \
  wireplumber.service filter-chain.service
```

Reverse:

```bash
systemctl --user unmask \
  pipewire.socket pipewire.service \
  pipewire-pulse.socket pipewire-pulse.service \
  wireplumber.service filter-chain.service
systemctl --user start pipewire.socket
```

Note these come back for any user whose session starts them. They exist at all
because Raspberry Pi OS auto-logs-in on tty1, which starts a user session even
with the desktop off. Disabling that autologin (`sudo raspi-config` → System
Options → Boot / Auto Login → **Console**) stops user services spawning at all,
at the cost of needing to log in on an attached keyboard. SSH is unaffected.

## 3. Disable printer discovery

```bash
sudo systemctl disable --now cups-browsed
```

Reverse:

```bash
sudo systemctl enable --now cups-browsed
```

## 4. Run gunicorn with one worker

Three workers each imported `wyze_sdk` separately, roughly 50MB apiece. One
worker is ample for a single-user light switch, and the shared token cache
(`.tokens.json`) means workers no longer need their own sessions anyway.

In `/etc/systemd/system/wyze-flask.service`:

```ini
ExecStart=/home/bronson/wyze/.venv/bin/gunicorn --workers 1 \
  --bind unix:wyze-flask.sock -m 007 main:app
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart wyze-flask
```

Reverse by setting `--workers 3` again, or restoring the backup taken when this
was changed:

```bash
sudo cp /etc/systemd/system/wyze-flask.service.bak \
        /etc/systemd/system/wyze-flask.service
sudo systemctl daemon-reload && sudo systemctl restart wyze-flask
```

## Considered but not done

**Merging the two processes.** `button.py` and the gunicorn worker each pay the
35MB `wyze_sdk` import. Attaching the GPIO listener inside the Flask worker
would save roughly 45MB — the largest remaining win.

It was not done because it costs failure isolation: today a crash in one does
not affect the other, which is exactly what made a past outage easy to
diagnose. It would also make `--workers 1` a correctness requirement rather
than a preference, since two workers would both try to claim GPIO 4.

## Measuring

`htop` and RSS both overstate usage, because shared pages are counted against
every process. PSS (proportional set size) divides shared pages among the
processes actually using them:

```bash
# PSS of the top processes
for p in $(ps -eo pid --no-headers --sort=-rss | head -10); do
  s=$(sudo awk '/^Pss:/{s+=$2} END{print s+0}' /proc/$p/smaps_rollup 2>/dev/null)
  [ "${s:-0}" -lt 1024 ] && continue
  printf "%6sMB  %s\n" "$((s/1024))" "$(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-44)"
done
```

```bash
free -h                    # swap in use is the signal that matters
systemd-cgtop -m           # memory by service
```

**Watch the swap column, not the used column.** Linux is expected to use most
of RAM; buff/cache is reclaimable. Sustained swap on a Pi means real pressure.
