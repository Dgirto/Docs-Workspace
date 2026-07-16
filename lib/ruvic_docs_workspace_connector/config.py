"""Configuración del conector leída desde variables de entorno.

Convención de la plataforma: cada campo del formulario de configuración
llega como variable de entorno {ENV_PREFIX}{CAMPO} en mayúsculas.
Para este conector el prefijo es RUVIC_DOCS_WORKSPACE_.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

ENV_PREFIX = "RUVIC_DOCS_WORKSPACE_"


@dataclass(frozen=True)
class DocsWorkspaceConfig:
    """Credenciales de la cuenta de servicio con delegación de dominio.

    Una sola credencial (esta cuenta de servicio) puede impersonar a
    cualquier usuario del dominio Google Workspace autorizado en el
    Admin Console y leer/crear/editar los documentos a los que ese
    usuario tenga acceso, sin necesidad de autorización individual ni
    tokens que expiren.
    """

    service_account_info: dict[str, Any]
    default_user: str
    request_timeout: int = 30

    @classmethod
    def from_env(cls) -> "DocsWorkspaceConfig":
        """Construye la configuración desde las variables RUVIC_DOCS_WORKSPACE_*.

        Raises:
            ValueError: si falta alguna variable obligatoria o el JSON de
                la cuenta de servicio no es válido.

        Ejemplo:
            >>> config = DocsWorkspaceConfig.from_env()
            >>> config.default_user
            'facturacion@tuempresa.com'
        """
        missing = [
            f"{ENV_PREFIX}{name}"
            for name in ("SERVICE_ACCOUNT_JSON", "DEFAULT_USER")
            if not os.environ.get(f"{ENV_PREFIX}{name}")
        ]
        if missing:
            raise ValueError(
                "Faltan variables de entorno del conector docs_workspace: "
                + ", ".join(missing)
                + ". Configura el conector en Settings -> Conectores."
            )

        raw_json = os.environ[f"{ENV_PREFIX}SERVICE_ACCOUNT_JSON"]
        try:
            info = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{ENV_PREFIX}SERVICE_ACCOUNT_JSON no contiene un JSON válido: {exc}. "
                "Verifica que copiaste el archivo de credenciales completo, sin "
                "recortar ni modificar su contenido."
            ) from exc

        missing_keys = [k for k in ("client_email", "private_key", "client_id") if k not in info]
        if missing_keys:
            raise ValueError(
                "El JSON de la cuenta de servicio no tiene el formato esperado "
                f"(faltan campos: {', '.join(missing_keys)}). Descárgalo de nuevo "
                "desde Google Cloud Console -> IAM y administración -> Cuentas de servicio."
            )

        return cls(
            service_account_info=info,
            default_user=os.environ[f"{ENV_PREFIX}DEFAULT_USER"],
            request_timeout=int(os.environ.get(f"{ENV_PREFIX}REQUEST_TIMEOUT", "30")),
        )
