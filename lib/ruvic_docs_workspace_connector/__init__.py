"""Conector Ruvic para Google Docs (Google Workspace) vía cuenta de
servicio con delegación de dominio."""

from .client import DocsWorkspaceClient
from .config import ENV_PREFIX, DocsWorkspaceConfig
from .exceptions import (
    DocsWorkspaceAuthError,
    DocsWorkspaceConnectorError,
    DocsWorkspaceDataError,
    DocsWorkspaceNetworkError,
)
from .logging_utils import setup_logging

__all__ = [
    "ENV_PREFIX",
    "DocsWorkspaceAuthError",
    "DocsWorkspaceClient",
    "DocsWorkspaceConfig",
    "DocsWorkspaceConnectorError",
    "DocsWorkspaceDataError",
    "DocsWorkspaceNetworkError",
    "setup_logging",
]

__version__ = "1.0.0"
