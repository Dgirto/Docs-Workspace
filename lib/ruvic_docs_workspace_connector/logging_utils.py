"""Logging configurable del conector. Nada de print()."""

from __future__ import annotations

import logging

_LOGGER_NAME = "ruvic_docs_workspace_connector"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configura y retorna el logger del conector.

    Args:
        level: "DEBUG", "INFO", "WARNING" o "ERROR".

    Ejemplo:
        >>> logger = setup_logging("DEBUG")
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(level.upper())
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
