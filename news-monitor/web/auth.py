"""HTTP Basic Auth middleware for the News Monitor web dashboard.

Reads credentials from ``WEB_USERNAME`` / ``WEB_PASSWORD`` environment
variables.  When ``WEB_USERNAME`` is unset or empty the middleware is a
transparent pass-through — no breaking change for local dev.

The ``/health`` and ``/api/health`` paths are excluded from auth so that
Docker HEALTHCHECK and external uptime monitors can probe without credentials.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AUTH_SKIP_PREFIXES = frozenset({"/health"})
_AUTH_SKIP_EXACT = frozenset({"/api/health"})


def _parse_credentials() -> Optional[tuple[str, str]]:
    """Return (username, password) or None if auth is not configured."""
    username = (os.environ.get("WEB_USERNAME") or "").strip()
    password = (os.environ.get("WEB_PASSWORD") or "").strip()
    if not username:  # auth disabled — transparent pass-through
        return None
    return username, password


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@web.middleware
async def basic_auth_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Require HTTP Basic Authentication for all requests except health checks."""

    # ----- skip auth for health endpoints -----
    if request.path in _AUTH_SKIP_EXACT or request.path.startswith("/health"):
        return await handler(request)

    creds = _parse_credentials()
    if creds is None:
        # Auth not configured — transparent pass-through
        return await handler(request)

    expected_username, expected_password = creds

    # ----- parse Authorization header -----
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return _unauthorized()

    try:
        encoded = auth_header[len("Basic "):]
        decoded = base64.b64decode(encoded).decode("utf-8", errors="strict")
        username, _, password = decoded.partition(":")
    except Exception:
        logger.debug("Basic auth: failed to decode credentials")
        return _unauthorized()

    # ----- constant-time comparison -----
    if not secrets.compare_digest(username, expected_username):
        logger.debug("Basic auth: username mismatch for %s", request.remote)
        return _unauthorized()
    if not secrets.compare_digest(password, expected_password):
        logger.debug("Basic auth: password mismatch for %s (user=%s)", request.remote, username)
        return _unauthorized()

    return await handler(request)


def _unauthorized() -> web.Response:
    return web.json_response(
        {"error": "Authentication required"},
        status=401,
        headers={
            "WWW-Authenticate": 'Basic realm="News Monitor Dashboard", charset="UTF-8"',
            "Access-Control-Allow-Origin": "*",
        },
    )
