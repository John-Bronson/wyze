"""Shared logging configuration for the web app and the button daemon.

Every process writes to its own file under logs/ and to stdout, so records are
readable both through the web UI (/logs) and with journalctl on the Pi.

stdout matters for a second reason: print() to a pipe is block-buffered, so the
button daemon's output only ever reached journald when it crashed and the
buffer flushed. logging emits each record immediately.
"""
import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

# Anything shaped like a JWT. Wyze access and refresh tokens are JWTs, and they
# are the credentials most likely to end up in a log line by accident.
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}")

_secrets: list = []


def _redact(text: str) -> str:
    for secret in _secrets:
        if secret and secret in text:
            text = text.replace(secret, "<redacted>")
    return _JWT_RE.sub("<jwt redacted>", text)


class _RedactFilter(logging.Filter):
    """Scrub credentials from every record, whoever emitted it.

    Applied to handlers rather than loggers so it also covers records from
    wyze_sdk and other libraries.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = _redact(message)
        record.args = ()
        return True


def setup_logging(component: str, level: int = logging.INFO) -> logging.Logger:
    """Configure root logging for this process. Safe to call more than once.

    `component` names the log file, so run one component per process:
    "web" for the Flask app, "button" for the GPIO daemon.
    """
    global _secrets
    # Read after load_dotenv() so the values are populated.
    _secrets = [os.getenv(name) for name in
                ("WYZE_PASSWORD", "WYZE_API_KEY", "WYZE_KEY_ID")]

    root = logging.getLogger()
    if getattr(root, "_wyze_configured", False):
        return logging.getLogger(component)

    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s pid=%(process)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers = [
        RotatingFileHandler(os.path.join(LOG_DIR, f"{component}.log"),
                            maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT),
        logging.StreamHandler(sys.stdout),
    ]
    for handler in handlers:
        handler.setFormatter(fmt)
        handler.addFilter(_RedactFilter())
        root.addHandler(handler)

    root.setLevel(level)
    # wyze_sdk logs the full request/response at DEBUG, including tokens.
    logging.getLogger("wyze_sdk").setLevel(logging.WARNING)
    root._wyze_configured = True
    return logging.getLogger(component)


def log_files() -> list:
    """Existing log files, newest activity first. Used by the /logs view."""
    if not os.path.isdir(LOG_DIR):
        return []
    names = [n for n in os.listdir(LOG_DIR) if n.endswith(".log")]
    return sorted(names, key=lambda n: os.path.getmtime(os.path.join(LOG_DIR, n)),
                  reverse=True)


def read_log(name: str, lines: int = 200) -> str:
    """Last `lines` of a log file. `name` is validated against log_files()."""
    if name not in log_files():
        return f"(no such log: {name})"
    path = os.path.join(LOG_DIR, name)
    with open(path, "r", errors="replace") as handle:
        content = handle.readlines()
    return "".join(content[-lines:]) or "(empty)"
