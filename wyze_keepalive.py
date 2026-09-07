"""Give wyze-sdk HTTP connection reuse.

wyze_sdk.service.base._do_request opens `with requests.Session() as client:`
for every API call, so each one pays a fresh TCP + TLS handshake. Measured on
this Pi Zero 2 W: 0.88s per call with a fresh session, 0.11s with a reused one
- 88% of each call was connection setup. A four-device button press makes nine
API calls, so that was roughly seven seconds of pure handshaking.

This replaces the `requests` name inside that one module with a shim whose
Session() hands back a per-thread session that ignores close().

Thread-local rather than one shared session: requests makes no thread-safety
guarantee, and the button daemon reads device states from a thread pool. Each
pool thread keeps its own warm connection, and because the pool is long-lived
those connections stay warm between button presses.

This reaches into SDK internals, so enable() verifies the shape it expects and
returns False without patching if a future version moves things.
"""
import logging
import threading

import requests

logger = logging.getLogger(__name__)

_local = threading.local()


class _KeepAliveSession(requests.Session):
    """A Session that survives `with ... as client:` - the SDK's context
    manager would otherwise close it, discarding the connection we want."""

    def close(self):  # noqa: D102 - deliberately does nothing
        pass

    def close_for_real(self):
        super().close()


def _thread_session() -> _KeepAliveSession:
    session = getattr(_local, "session", None)
    if session is None:
        session = _KeepAliveSession()
        _local.session = session
        logger.debug("new keep-alive session for thread %s",
                     threading.current_thread().name)
    return session


class _RequestsShim:
    """Stands in for the `requests` module inside wyze_sdk.service.base.

    Only Session is replaced; every other attribute falls through to the real
    module, so anything else that module reaches for keeps working.
    """

    Session = staticmethod(_thread_session)

    def __getattr__(self, name):
        return getattr(requests, name)


def enable() -> bool:
    """Patch the SDK for connection reuse. Returns True if it took effect."""
    try:
        from wyze_sdk.service import base
    except Exception as err:
        logger.warning("could not import wyze_sdk.service.base (%s); "
                       "leaving HTTP handling alone", err)
        return False

    if getattr(base, "_wyze_keepalive_installed", False):
        return True

    # Only patch if the module looks the way we expect.
    target = getattr(base, "requests", None)
    if target is None or not hasattr(target, "Session"):
        logger.warning("wyze_sdk.service.base does not use `requests` the way "
                       "this patch expects; leaving HTTP handling alone")
        return False

    base.requests = _RequestsShim()
    base._wyze_keepalive_installed = True
    logger.info("HTTP keep-alive enabled for wyze_sdk (thread-local sessions)")
    return True
