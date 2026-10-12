#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Uniform JSON error responses: a generic category plus the request id that finds the log line."""

import logging
import traceback

import werkzeug.exceptions
from flask import Flask, g, has_request_context, jsonify, request

# Local imports
from libs import config, metrics

logger = logging.getLogger(__name__)


def get_request_id() -> str:
    """Return the id assigned to the current request, or "-" when called outside one.

    Background threads (the job worker) call code that logs with a request id and have no request.
    """
    if not has_request_context():
        return "-"
    return getattr(g, "request_id", "-")


def build_error_response(error: str, status: int, **extra):
    """Build the project-wide error body: the error category, the request id and nothing else.

    Details never reach the client - the full exception goes to the log under the
    same request id, so a report can be correlated without leaking internals.
    """
    metrics.count_error(error)
    body = {"error": error, "request_id": get_request_id()}
    body.update(extra)
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    """Attach every error handler to the application so all failures share one response shape."""

    @app.errorhandler(400)
    def bad_request(error):
        """Return the generic body for a malformed request."""
        logger.warning("[%s] Bad Request: %s", get_request_id(), error)
        return build_error_response("Bad Request", 400)

    @app.errorhandler(404)
    def not_found(error):
        """Return the generic body for an unknown route."""
        return build_error_response("Not Found", 404)

    @app.errorhandler(405)
    def method_not_allowed(error):
        """Return the generic body for a method the route does not accept, with the Allow header.

        RFC 9110 requires Allow on a 405, and it is what tells a client which method to use
        instead; werkzeug knows the route's methods and passes them on the exception.
        """
        response, status = build_error_response("Method Not Allowed", 405)
        valid_methods = getattr(error, "valid_methods", None)
        if valid_methods:
            response.headers["Allow"] = ", ".join(sorted(valid_methods))
        return response, status

    @app.errorhandler(413)
    def payload_too_large(error):
        """Return the generic body plus the configured upload limit."""
        # The route's own limit: /api/jobs takes far larger files than the synchronous endpoints.
        limit = request.max_content_length or config.MAX_CONTENT_LENGTH_MB * 1024 * 1024
        limit_mb = limit // (1024 * 1024)
        logger.warning("[%s] Payload too large (limit=%dMB)", get_request_id(), limit_mb)
        return build_error_response("Payload Too Large", 413, limit_mb=limit_mb)

    @app.errorhandler(500)
    def internal_error(error):
        """Log the failure with its traceback and return the generic body."""
        logger.error(
            "[%s] Internal Server Error: %s: %s\n%s",
            get_request_id(),
            type(error).__name__,
            error,
            traceback.format_exc(),
        )
        return build_error_response("Internal Server Error", 500)

    @app.errorhandler(Exception)
    def handle_exception(exception):
        """Catch everything left: pass HTTP errors through, log the rest as a 500."""
        if isinstance(exception, werkzeug.exceptions.HTTPException):
            logger.warning("[%s] %s: %s", get_request_id(), exception.name, exception.description)
            return build_error_response(exception.name, exception.code)

        logger.error(
            "[%s] Unhandled exception: %s: %s\n%s",
            get_request_id(),
            type(exception).__name__,
            exception,
            traceback.format_exc(),
        )
        return build_error_response("Internal Server Error", 500)


def main():
    """No-op entry point: this module is imported for its error helpers."""
    pass


if __name__ == "__main__":
    main()
