from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Settings


def configure_logging(settings: Settings) -> logging.Logger:
    logger = logging.getLogger("maker")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    logger.info("Logging initialized at %s", settings.log_file)
    return logger
