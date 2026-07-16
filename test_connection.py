"""Prueba de conexión estándar del conector docs_workspace.

Firma estándar Ruvic: def test_connection() -> tuple[bool, str]
- Lee la configuración EXCLUSIVAMENTE de las env vars RUVIC_DOCS_WORKSPACE_*.
- Nunca lanza excepciones; retorna (ok, mensaje).

Ejecutable también como script para pruebas locales:
    python test_connection.py
"""

from __future__ import annotations


def test_connection() -> tuple[bool, str]:
    """Verifica la delegación de dominio impersonando al usuario de prueba
    (RUVIC_DOCS_WORKSPACE_DEFAULT_USER)."""
    try:
        from ruvic_docs_workspace_connector import (
            DocsWorkspaceAuthError,
            DocsWorkspaceClient,
            DocsWorkspaceConfig,
            DocsWorkspaceDataError,
            DocsWorkspaceNetworkError,
        )
    except ImportError:
        return (
            False,
            "La librería ruvic-docs-workspace-connector no está instalada. "
            "Instala con: pip install git+https://github.com/Dgirto/"
            "Docs-Workspace.git#subdirectory=lib",
        )

    try:
        config = DocsWorkspaceConfig.from_env()
    except ValueError as exc:
        return False, str(exc)

    try:
        client = DocsWorkspaceClient(user_email=config.default_user, config=config)
    except DocsWorkspaceDataError as exc:
        return False, str(exc)

    try:
        client.ping()
    except DocsWorkspaceAuthError as exc:
        return False, f"Autenticación fallida: {exc}"
    except DocsWorkspaceNetworkError as exc:
        return False, f"Error de red: {exc}"
    except DocsWorkspaceDataError as exc:
        return False, f"Error de datos: {exc}"
    except Exception as exc:  # red de seguridad: jamás propagar
        return False, f"Error inesperado: {exc}"

    return (
        True,
        f"Conexión exitosa como {config.default_user} (delegación de dominio)",
    )


if __name__ == "__main__":
    ok, message = test_connection()
    print(f"{'OK' if ok else 'FALLO'}: {message}")
    raise SystemExit(0 if ok else 1)
