#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logging setup: one format for the application, uvicorn and the CLI entry points."""

import logging
from typing import Any

# Local imports
from libs import config

LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s.%(funcName)s) %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = config.LOG_LEVEL) -> None:
    """Configure the root logger with the project-wide format; a no-op if already configured."""
    logging.basicConfig(
        handlers=[logging.StreamHandler()],
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=getattr(logging, level, logging.INFO),
    )


def build_uvicorn_log_config(level: str = config.LOG_LEVEL) -> dict[str, Any]:
    """Build a uvicorn dictConfig that reuses the project format and mutes its own access log.

    Uvicorn installs its own handlers unless it is handed a config, which would
    print request lines in a shape that does not match the rest of the service.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": LOG_FORMAT,
                "datefmt": LOG_DATE_FORMAT,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": [], "propagate": False},
        },
    }


def main():
    """No-op entry point: this module is imported for its logging helpers."""
    pass


if __name__ == "__main__":
    main()
