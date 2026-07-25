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


def is_valid_token(token: str) -> bool:
    """Compare the token against every configured one in constant time."""
    return bool(token) and any(hmac.compare_digest(token, valid) for valid in config.STT_TOKENS)


def token_required(view):
    """Reject requests without a valid Bearer token; a pass-through while STT_TOKENS is empty."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        """Check the Authorization header, then delegate to the wrapped view."""
        if not config.STT_TOKENS:
            return view(*args, **kwargs)
        if not is_valid_token(read_bearer_token()):
            logger.warning("[%s] Unauthorized", get_request_id())
            return build_error_response("Unauthorized", 401)
        return view(*args, **kwargs)

    return wrapper


def main():
    """No-op entry point: this module is imported for its auth decorator."""
    pass


if __name__ == "__main__":
    main()
