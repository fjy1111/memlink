"""Unified logging helpers."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once and keep third-party output readable."""

    root = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Create a named logger using the shared configuration."""

    return logging.getLogger(name)
