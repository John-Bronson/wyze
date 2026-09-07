"""Wyze authentication: acquire, cache, refresh and persist session tokens.

History worth keeping in mind, because it caused a silent hourly outage:

  * Wyze's login response carries no `expires_in`, so the old code defaulted to
    3600 and believed a token was stale after 55 minutes. The JWT's own `exp`
    claim says 48 hours. Expiry is now read from the token itself.
  * The refresh client was built as Client(token=...) with no refresh_token, so
    the SDK raised WyzeClientConfigurationError("client is not logged in").
  * That error is NOT a subclass of WyzeApiError, so `except WyzeApiError`
    never caught it. It escaped every route as a 500 and killed the button
    daemon outright. Both paths now catch WyzeClientError as well.
  * Login puts tokens at the top level; refresh nests them under "data".
    _extract_tokens() handles either shape.
"""
import base64
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from dotenv import load_dotenv
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError, WyzeClientError

load_dotenv()

logger = logging.getLogger(__name__)

# Tokens are cached here so the gunicorn workers and the button daemon share one
# session instead of logging in separately, and so a restart does not re-login.
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tokens.json")

# Refresh this long before actual expiry.
EXPIRY_BUFFER = timedelta(minutes=5)
# Used only when a token carries no readable exp claim.
FALLBACK_LIFETIME = 3600


def _jwt_expiry(token: str) -> Optional[datetime]:
    """Read the `exp` claim from a JWT without verifying it.

    Not a security check - we already trust the token, we only want to know
    when Wyze will stop accepting it. Signature verification would need Wyze's
    public key and buys us nothing here.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # restore stripped base64 padding
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return datetime.fromtimestamp(float(claims["exp"]), tz=timezone.utc)
    except Exception as err:
        logger.debug("could not read exp claim from token: %s", err)
        return None


def _extract_tokens(response) -> Mapping:
    """Return the mapping holding the tokens, for either response shape."""
    try:
        inner = response["data"]
        if inner and "access_token" in inner:
            return inner
    except Exception:
        pass
    return response


class TokenManager:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = None
        self.client = None
        self._lock = threading.Lock()
        self._email = os.environ.get('WYZE_EMAIL')
        self._password = os.environ.get('WYZE_PASSWORD')
        self._key_id = os.environ.get('WYZE_KEY_ID')
        self._api_key = os.environ.get('WYZE_API_KEY')

    # ---------------------------------------------------------------- storage

    def _load_from_disk(self) -> bool:
        """Adopt tokens another process cached. Returns True if usable."""
        try:
            with open(TOKEN_FILE, "r") as handle:
                stored = json.load(handle)
        except FileNotFoundError:
            return False
        except (json.JSONDecodeError, OSError) as err:
            logger.warning("token cache unreadable (%s); ignoring it", err)
            return False

        access = stored.get("access_token")
        refresh = stored.get("refresh_token")
        expires = stored.get("expires_at")
        if not access or not refresh or not expires:
            return False

        expires_at = datetime.fromtimestamp(float(expires), tz=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at - EXPIRY_BUFFER:
            logger.info("cached token expired at %s; ignoring it",
                        expires_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"))
            return False

        self.access_token, self.refresh_token, self.expires_at = access, refresh, expires_at
        self.client = Client(token=access, refresh_token=refresh)
        logger.info("adopted cached token from %s, valid until %s",
                    os.path.basename(TOKEN_FILE),
                    expires_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"))
        return True

    def _save_to_disk(self):
        """Write the cache atomically, owner-readable only."""
        payload = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.timestamp(),
            "written_at": time.time(),
        }
        tmp = f"{TOKEN_FILE}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w") as handle:
                json.dump(payload, handle)
            os.chmod(tmp, 0o600)
            os.replace(tmp, TOKEN_FILE)  # atomic: readers never see a partial file
            logger.debug("token cache written to %s", TOKEN_FILE)
        except OSError as err:
            logger.warning("could not write token cache: %s", err)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ------------------------------------------------------------------- auth

    def _login(self):
        logger.info("logging in to Wyze as %s", self._email)
        started = time.monotonic()
        try:
            response = Client().login(
                email=self._email,
                password=self._password,
                key_id=self._key_id,
                api_key=self._api_key,
            )
        except (WyzeApiError, WyzeClientError) as err:
            logger.error("login FAILED after %.1fs: %s: %s",
                         time.monotonic() - started, type(err).__name__, err)
            logger.error("if this is HTTP 400 / errorCode 1000, regenerate BOTH "
                         "WYZE_KEY_ID and WYZE_API_KEY together - they are a "
                         "matched pair (see .env.example)")
            raise
        logger.info("login succeeded in %.1fs", time.monotonic() - started)
        self._adopt(response)

    def _refresh(self):
        logger.info("refreshing access token")
        started = time.monotonic()
        try:
            # Both tokens must be passed: the SDK refuses to refresh a client
            # that has no refresh token, and that refusal is not a WyzeApiError.
            temp_client = Client(token=self.access_token,
                                 refresh_token=self.refresh_token)
            response = temp_client.refresh_token()
        except (WyzeApiError, WyzeClientError) as err:
            logger.warning("refresh failed after %.1fs (%s: %s); falling back "
                           "to a full login",
                           time.monotonic() - started, type(err).__name__, err)
            self._login()
            return
        logger.info("refresh succeeded in %.1fs", time.monotonic() - started)
        self._adopt(response)

    def _adopt(self, response):
        """Store tokens from a login or refresh response and rebuild the client."""
        tokens = _extract_tokens(response)
        try:
            self.access_token = tokens["access_token"]
            self.refresh_token = tokens["refresh_token"]
        except (KeyError, TypeError) as err:
            keys = list(tokens.keys()) if hasattr(tokens, "keys") else type(tokens).__name__
            logger.error("auth response missing tokens (%s); keys present: %s", err, keys)
            raise

        expiry = _jwt_expiry(self.access_token)
        if expiry:
            self.expires_at = expiry
            source = "exp claim"
        else:
            lifetime = int(tokens.get("expires_in", FALLBACK_LIFETIME)) \
                if hasattr(tokens, "get") else FALLBACK_LIFETIME
            self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
            source = f"fallback {lifetime}s"

        self.client = Client(token=self.access_token, refresh_token=self.refresh_token)
        logger.info("token valid until %s (%s), %s from now",
                    self.expires_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
                    source, self._time_remaining())
        self._save_to_disk()

    # ----------------------------------------------------------------- public

    def _time_remaining(self, expires_at=None) -> str:
        expires_at = expires_at or self.expires_at
        if not expires_at:
            return "unknown"
        seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
        if seconds < 0:
            return "expired"
        hours, remainder = divmod(int(seconds), 3600)
        return f"{hours}h{remainder // 60:02d}m"

    def _cached_expiry(self) -> Optional[datetime]:
        """Expiry recorded in the shared cache, without adopting the token."""
        try:
            with open(TOKEN_FILE, "r") as handle:
                stored = json.load(handle)
            return datetime.fromtimestamp(float(stored["expires_at"]), tz=timezone.utc)
        except Exception:
            return None

    def is_token_expired(self) -> bool:
        if not self.access_token or not self.expires_at:
            return True
        return datetime.now(timezone.utc) >= self.expires_at - EXPIRY_BUFFER

    def get_client(self) -> Client:
        """Return an authenticated client, refreshing or logging in as needed."""
        with self._lock:
            if not self.is_token_expired():
                return self.client

            # Another worker may have refreshed while this one was idle.
            if self._load_from_disk():
                return self.client

            if self.refresh_token:
                logger.info("token expired or missing; refreshing")
                self._refresh()
            else:
                logger.info("no refresh token available; logging in")
                self._login()
            return self.client

    def status(self) -> dict:
        """Token state for the /logs view. Contains no token material.

        A worker that has not served a request yet holds no token in memory
        while a perfectly good one sits in the shared cache, so report both
        rather than claiming the app is unauthenticated.
        """
        expires_at, source = self.expires_at, "this process"
        if not self.access_token:
            expires_at, source = self._cached_expiry(), "shared cache"
        if expires_at is None:
            source = "none"
        return {
            "token_source": source,
            "authenticated_in_this_process": bool(self.access_token),
            "expires_at": expires_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
                          if expires_at else None,
            "time_remaining": self._time_remaining(expires_at),
            "needs_refresh": expires_at is None
                             or datetime.now(timezone.utc) >= expires_at - EXPIRY_BUFFER,
            "cache_file": TOKEN_FILE if os.path.exists(TOKEN_FILE) else "(absent)",
            "pid": os.getpid(),
        }


token_manager = TokenManager()


if __name__ == "__main__":
    from logging_setup import setup_logging
    setup_logging("cli")
    logger.info("running token_manager.py directly as a check")
    client = token_manager.get_client()
    logger.info("status: %s", token_manager.status())
    for device in client.devices_list():
        logger.info("  %s (%s) %s", device.nickname, device.mac,
                    "online" if device.is_online else "offline")
    logger.info("requesting the client again (should reuse, not re-login)")
    token_manager.get_client()
