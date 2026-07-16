"""Excepciones propias del conector Docs Workspace.

Separan los tres tipos de fallo que el usuario debe distinguir:
autenticación, red/servidor y datos. Nunca exponemos excepciones
crípticas del cliente HTTP subyacente.
"""


class DocsWorkspaceConnectorError(Exception):
    """Error base del conector."""


class DocsWorkspaceAuthError(DocsWorkspaceConnectorError):
    """Credenciales inválidas o delegación de dominio no autorizada para el usuario impersonado."""


class DocsWorkspaceNetworkError(DocsWorkspaceConnectorError):
    """No se pudo alcanzar la API de Docs (red, timeout, error temporal del servidor)."""


class DocsWorkspaceDataError(DocsWorkspaceConnectorError):
    """La operación es válida pero el recurso no existe o los datos son inválidos."""
