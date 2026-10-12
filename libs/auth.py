#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional static-token authentication for the transcription endpoint."""

import hmac
import logging
from functools import wraps

from flask import request

# Local imports
from libs import config
from libs.errors import build_error_response, get_request_id

logger = logging.getLogger(__name__)

BEARER_PREFIX = "Bearer "


def read_bearer_token() -> str:
    """Extract the token from the Authorization header, or "" when it is absent or malformed."""
    header = request.headers.get("Authorization", "")
    if not header.startswith(BEARER_PREFIX):
        return ""
    return header[len(BEARER_PREFIX) :].strip()


def encode_token(token: str) -> bytes | None:
    """A token as UTF-8 bytes, or None for a str that UTF-8 cannot carry.

    `surrogateescape` restores the bytes an environment value was decoded from, but it still
    raises on a lone surrogate outside U+DC80..U+DCFF, which a JSON start message on
    /api/stream can hold (`"\\ud800"`). Such a token matches nothing.
    """
    try:
        return token.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return None


def is_valid_token(token: str) -> bool:
    """Compare the token against every configured one in constant time.

    Both sides are compared as UTF-8 bytes: hmac.compare_digest raises TypeError on a str
    with non-ASCII characters, which would turn a stray header into a 500.
    """
    token_bytes = encode_token(token) if token else None
    if not token_bytes:
        return False
    valid_tokens = [encode_token(valid) for valid in config.STT_TOKENS]
    return any(hmac.compare_digest(token_bytes, valid) for valid in valid_tokens if valid is not None)


def is_request_authorized() -> bool:
    """Whether the current request would pass token_required: auth is off, or it carries a valid token."""
    return not config.STT_TOKENS or is_valid_token(read_bearer_token())


def token_required(view):
    """Reject requests without a valid Bearer token; a pass-through while STT_TOKENS is empty."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        """Check the Authorization header, then delegate to the wrapped view."""
        if not is_request_authorized():
            logger.warning("[%s] Unauthorized", get_request_id())
            return build_error_response("Unauthorized", 401)
        return view(*args, **kwargs)

    return wrapper


def main():
    """No-op entry point: this module is imported for its auth decorator."""
    pass


if __name__ == "__main__":
    main()
