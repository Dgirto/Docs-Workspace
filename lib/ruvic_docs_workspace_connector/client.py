"""Cliente de Google Docs (Google Workspace) vía cuenta de servicio con
delegación de dominio.

Mismo patrón de autenticación que ruvic_drive_connector (CON-007) y
ruvic_sheets_workspace_connector (CON-006.1): el constructor recibe el
usuario del dominio a impersonar, y una sola credencial (esta cuenta de
servicio) puede actuar como cualquier usuario autorizado del dominio
sin volver a autorizar por usuario ni gestionar expiración de tokens.

Capacidades:
- read_document():   leer el título y el texto completo de un documento.
- create_document():  crear un documento nuevo (con texto inicial opcional).
- append_text():      agregar texto al final de un documento.
- replace_text():     buscar y reemplazar texto en todo el documento.
- create_from_template(): copiar una plantilla y reemplazar sus variables
                      en la copia (la plantilla no se modifica).
- export_pdf():       exportar un documento a PDF en disco local.

create_from_template() y export_pdf() usan la API de Drive, por eso la
delegación de dominio debe autorizar los scopes documents y drive.

Las credenciales SIEMPRE provienen de variables de entorno
RUVIC_DOCS_WORKSPACE_* (ver config.DocsWorkspaceConfig.from_env).
Prohibido hardcodearlas.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .config import DocsWorkspaceConfig
from .exceptions import (
    DocsWorkspaceAuthError,
    DocsWorkspaceConnectorError,
    DocsWorkspaceDataError,
    DocsWorkspaceNetworkError,
)
from .logging_utils import get_logger

_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
_DOC_MIME = "application/vnd.google-apps.document"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _service_disabled_info(exc: HttpError) -> tuple[str, str] | None:
    """Detecta el caso 403 SERVICE_DISABLED (la API no está habilitada en
    el proyecto de Google Cloud) y retorna (nombre de la API, URL de
    activación), o None si el error es de otro tipo."""
    try:
        details = exc.error_details or []
    except Exception:
        details = []
    for detail in details:
        if isinstance(detail, dict) and detail.get("reason") == "SERVICE_DISABLED":
            meta = detail.get("metadata", {})
            return (
                meta.get("serviceTitle", "API de Google"),
                meta.get(
                    "activationUrl",
                    "Google Cloud Console -> APIs y servicios -> Biblioteca",
                ),
            )
    return None


def _wrap_http_error(exc: HttpError) -> DocsWorkspaceConnectorError:
    """Traduce un error HTTP de la API de Docs a una excepción propia,
    sin dejar escapar nunca el tipo crudo del cliente HTTP."""
    status = exc.resp.status if getattr(exc, "resp", None) is not None else None
    if status == 403:
        disabled = _service_disabled_info(exc)
        if disabled is not None:
            service_title, activation_url = disabled
            return DocsWorkspaceAuthError(
                f"La {service_title} no está habilitada en el proyecto de "
                f"Google Cloud del Client ID configurado. Habilítala en "
                f"{activation_url} y espera 1-2 minutos antes de reintentar."
            )
    if status in (401, 403):
        return DocsWorkspaceAuthError(
            "Credenciales inválidas o sin permiso suficiente sobre este "
            "documento. Verifica que el Client ID de la cuenta de servicio "
            "esté autorizado en el Admin Console de Workspace con los scopes "
            "documents y drive, y que el usuario impersonado tenga acceso al "
            "documento."
        )
    if status == 404:
        return DocsWorkspaceDataError(
            "El documento solicitado no existe, o el usuario impersonado "
            "no tiene acceso a él."
        )
    if status == 429 or (status is not None and status >= 500):
        return DocsWorkspaceNetworkError(
            f"Docs API no respondió correctamente (HTTP {status}). "
            "Puede ser un límite de cuota temporal; reintenta en unos segundos."
        )
    return DocsWorkspaceDataError(f"Error de Docs API (HTTP {status}): {exc}")


def _validate_document_id(document_id: str) -> str:
    if not isinstance(document_id, str):
        raise DocsWorkspaceDataError(
            f"document_id debe ser un string, no {type(document_id).__name__}."
        )
    document_id = document_id.strip()
    if not document_id:
        raise DocsWorkspaceDataError("document_id no puede estar vacío.")
    return document_id


def _validate_text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise DocsWorkspaceDataError(f"{name} debe ser un string, no {type(value).__name__}.")
    if not value:
        raise DocsWorkspaceDataError(f"{name} no puede estar vacío.")
    return value


def _validate_str_type(value: Any, name: str) -> str:
    """Como _validate_text pero permite string vacío (ej. 'replace' al borrar texto)."""
    if not isinstance(value, str):
        raise DocsWorkspaceDataError(f"{name} debe ser un string, no {type(value).__name__}.")
    return value


def _extract_text(content: list[dict[str, Any]]) -> str:
    """Recorre los elementos estructurales de un documento y concatena el
    texto de párrafos y tablas, en orden."""
    parts: list[str] = []
    for element in content:
        if "paragraph" in element:
            for pe in element["paragraph"].get("elements", []):
                text = pe.get("textRun", {}).get("content")
                if text:
                    parts.append(text)
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    parts.append(_extract_text(cell.get("content", [])))
        elif "tableOfContents" in element:
            parts.append(_extract_text(element["tableOfContents"].get("content", [])))
    return "".join(parts)


class DocsWorkspaceClient:
    """Cliente de Google Docs para un usuario específico de un dominio
    Google Workspace, vía cuenta de servicio con delegación de dominio.

    Args:
        user_email: correo del usuario del dominio a impersonar (ej.
            "facturacion@tuempresa.com"). La cuenta de servicio debe estar
            autorizada en el Admin Console para el dominio de ese correo.
            El conector opera sobre los documentos a los que ese usuario
            tenga acceso (propios o compartidos con él).
        config: configuración de conexión. Si se omite, se lee de las
            variables de entorno RUVIC_DOCS_WORKSPACE_* (comportamiento
            estándar en el runtime de la plataforma).

    Ejemplo:
        >>> client = DocsWorkspaceClient(user_email="facturacion@tuempresa.com")
        >>> client.read_document("1AbC...xyz")
        {'id': '1AbC...xyz', 'title': 'Acta de reunión', 'body_text': '...'}
    """

    def __init__(self, user_email: str, config: DocsWorkspaceConfig | None = None) -> None:
        if not _EMAIL_RE.match(user_email):
            raise DocsWorkspaceDataError(
                f"user_email={user_email!r} no parece un correo válido "
                "(ej. 'facturacion@tuempresa.com')."
            )
        self.user_email = user_email
        self.config = config or DocsWorkspaceConfig.from_env()
        self._logger = get_logger()
        self._service: Any = None
        self._drive_service: Any = None
        self._credentials: service_account.Credentials | None = None

    # ------------------------------------------------------------------ #
    # Conexión
    # ------------------------------------------------------------------ #

    def _get_credentials(self) -> service_account.Credentials:
        if self._credentials is not None:
            return self._credentials
        try:
            self._credentials = service_account.Credentials.from_service_account_info(
                self.config.service_account_info,
                scopes=_SCOPES,
                subject=self.user_email,
            )
        except (ValueError, KeyError) as exc:
            raise DocsWorkspaceAuthError(
                f"El JSON de la cuenta de servicio es inválido o le faltan campos: {exc}"
            ) from exc
        return self._credentials

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service
        credentials = self._get_credentials()
        try:
            self._service = build(
                "docs",
                "v1",
                credentials=credentials,
                cache_discovery=False,
                static_discovery=False,
            )
        except (GoogleAuthError, OSError) as exc:
            raise DocsWorkspaceNetworkError(
                f"No se pudo inicializar el cliente de Docs: {exc}"
            ) from exc
        return self._service

    def _get_drive_service(self) -> Any:
        """Cliente de Drive v3, necesario para copiar plantillas y exportar a PDF."""
        if self._drive_service is not None:
            return self._drive_service
        try:
            self._drive_service = build(
                "drive",
                "v3",
                credentials=self._get_credentials(),
                cache_discovery=False,
                static_discovery=False,
            )
        except (GoogleAuthError, OSError) as exc:
            raise DocsWorkspaceNetworkError(
                f"No se pudo inicializar el cliente de Drive: {exc}"
            ) from exc
        return self._drive_service

    def ping(self) -> bool:
        """Verifica la delegación de dominio refrescando el token de
        acceso para el usuario impersonado (no requiere un documento
        específico).

        Returns:
            True si la conexión y la delegación funcionan.

        Raises:
            DocsWorkspaceAuthError / DocsWorkspaceNetworkError / DocsWorkspaceDataError.
        """
        credentials = self._get_credentials()
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            client_id = self.config.service_account_info.get("client_id", "?")
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar como {self.user_email!r} (unauthorized_client). "
                "Revisa en el Admin Console de Google Workspace (Seguridad -> Control "
                "de acceso a las API -> Delegación en todo el dominio) que: "
                f"1) el Client ID '{client_id}' esté agregado, "
                "2) los scopes autorizados incluyan exactamente "
                "'https://www.googleapis.com/auth/documents' y "
                "'https://www.googleapis.com/auth/drive', y 3) el usuario "
                "pertenezca a ese mismo dominio."
            ) from exc
        except (socket.error, TimeoutError, OSError) as exc:
            raise DocsWorkspaceNetworkError(
                f"No se pudo conectar con Docs API: {exc}"
            ) from exc
        self._logger.info("Ping exitoso, usuario: %s", self.user_email)
        return True

    # ------------------------------------------------------------------ #
    # Capacidad 1 — Leer un documento
    # ------------------------------------------------------------------ #

    def read_document(self, document_id: str) -> dict[str, Any]:
        """Lee el título y el texto completo de un documento.

        Args:
            document_id: ID del documento (de la URL:
                docs.google.com/document/d/{document_id}/edit).

        Returns:
            Dict con: id, title, body_text (texto plano, incluye el
            contenido de tablas en orden de aparición).

        Ejemplo:
            >>> client.read_document("1AbC...xyz")
            {'id': '1AbC...xyz', 'title': 'Acta de reunión', 'body_text': '...'}
        """
        document_id = _validate_document_id(document_id)
        service = self._get_service()
        try:
            doc = service.documents().get(documentId=document_id).execute(num_retries=1)
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        body_text = _extract_text(doc.get("body", {}).get("content", []))
        self._logger.info(
            "Leído documento %s (%d caracteres, usuario %s)",
            document_id, len(body_text), self.user_email,
        )
        return {
            "id": doc.get("documentId"),
            "title": doc.get("title", ""),
            "body_text": body_text,
        }

    # ------------------------------------------------------------------ #
    # Capacidad 2 — Crear un documento nuevo
    # ------------------------------------------------------------------ #

    def create_document(self, title: str, body_text: str | None = None) -> dict[str, Any]:
        """Crea un documento nuevo en el Drive del usuario impersonado.

        Args:
            title: título del documento.
            body_text: texto inicial del cuerpo (opcional).

        Returns:
            Dict con: id, title, url del documento creado.

        Ejemplo:
            >>> client.create_document("Acta de reunión", "Asistentes: ...")
            {'id': '1AbC...xyz', 'title': 'Acta de reunión', 'url': 'https://docs.google.com/document/d/1AbC...xyz/edit'}
        """
        title = _validate_text(title, "title")
        service = self._get_service()
        try:
            doc = service.documents().create(body={"title": title}).execute(num_retries=1)
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        document_id = doc["documentId"]
        if body_text:
            try:
                service.documents().batchUpdate(
                    documentId=document_id,
                    body={
                        "requests": [
                            {
                                "insertText": {
                                    "endOfSegmentLocation": {},
                                    "text": body_text,
                                }
                            }
                        ]
                    },
                ).execute(num_retries=1)
            except HttpError as exc:
                raise _wrap_http_error(exc) from exc
        self._logger.info(
            "Documento '%s' creado (id=%s, usuario %s)", title, document_id, self.user_email
        )
        return {
            "id": document_id,
            "title": doc.get("title", title),
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
        }

    # ------------------------------------------------------------------ #
    # Capacidad 3 — Agregar texto al final
    # ------------------------------------------------------------------ #

    def append_text(self, document_id: str, text: str) -> dict[str, Any]:
        """Agrega texto al final del cuerpo del documento.

        Args:
            document_id: ID del documento.
            text: texto a agregar (usa "\\n" para saltos de párrafo).

        Returns:
            Dict con: id, appended_chars.

        Ejemplo:
            >>> client.append_text("1AbC...xyz", "\\nNuevo párrafo al final.")
            {'id': '1AbC...xyz', 'appended_chars': 25}
        """
        document_id = _validate_document_id(document_id)
        text = _validate_text(text, "text")
        service = self._get_service()
        try:
            service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {"insertText": {"endOfSegmentLocation": {}, "text": text}}
                    ]
                },
            ).execute(num_retries=1)
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        self._logger.info(
            "Agregados %d caracteres al documento %s (usuario %s)",
            len(text), document_id, self.user_email,
        )
        return {"id": document_id, "appended_chars": len(text)}

    # ------------------------------------------------------------------ #
    # Capacidad 4 — Buscar y reemplazar texto
    # ------------------------------------------------------------------ #

    def replace_text(
        self,
        document_id: str,
        find: str,
        replace: str,
        match_case: bool = True,
    ) -> dict[str, Any]:
        """Reemplaza todas las ocurrencias de un texto en el documento.

        Args:
            document_id: ID del documento.
            find: texto a buscar (literal, no expresión regular).
            replace: texto de reemplazo.
            match_case: si distingue mayúsculas/minúsculas (default True).

        Returns:
            Dict con: id, occurrences_changed.

        Ejemplo:
            >>> client.replace_text("1AbC...xyz", "{{CLIENTE}}", "ACME S.A.")
            {'id': '1AbC...xyz', 'occurrences_changed': 3}
        """
        document_id = _validate_document_id(document_id)
        find = _validate_text(find, "find")
        replace = _validate_str_type(replace, "replace")
        service = self._get_service()
        try:
            result = service.documents().batchUpdate(
                documentId=document_id,
                body={
                    "requests": [
                        {
                            "replaceAllText": {
                                "containsText": {"text": find, "matchCase": match_case},
                                "replaceText": replace,
                            }
                        }
                    ]
                },
            ).execute(num_retries=1)
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc
        replies = result.get("replies", [{}])
        occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
        self._logger.info(
            "Reemplazadas %d ocurrencias de %r en %s (usuario %s)",
            occurrences, find, document_id, self.user_email,
        )
        return {"id": document_id, "occurrences_changed": occurrences}

    # ------------------------------------------------------------------ #
    # Capacidad 5 — Crear un documento a partir de una plantilla
    # ------------------------------------------------------------------ #

    def create_from_template(
        self,
        template_id: str,
        title: str,
        replacements: dict[str, str] | None = None,
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Copia una plantilla y reemplaza sus variables en la copia.

        La plantilla original nunca se modifica: los reemplazos se aplican
        solo sobre el documento nuevo.

        Args:
            template_id: ID del documento plantilla.
            title: título del documento nuevo.
            replacements: marcador -> valor (ej. {"{{CLIENTE}}": "ACME S.A."}).
                Distingue mayúsculas/minúsculas.
            parent_folder_id: carpeta de Drive destino (default: la raíz).

        Returns:
            Dict con: id, title, url, template_id, replacements (marcador ->
            ocurrencias reemplazadas; 0 indica un marcador no encontrado).

        Ejemplo:
            >>> client.create_from_template("1Tpl...", "Contrato ACME", {"{{CLIENTE}}": "ACME S.A."})
            {'id': '1New...', 'title': 'Contrato ACME', 'url': '...', 'template_id': '1Tpl...', 'replacements': {'{{CLIENTE}}': 2}}
        """
        template_id = _validate_document_id(template_id)
        title = title.strip()
        if not title:
            raise DocsWorkspaceDataError("title no puede estar vacío.")
        replacements = replacements or {}
        if not isinstance(replacements, dict) or not all(
            isinstance(k, str) and k for k in replacements
        ):
            raise DocsWorkspaceDataError(
                "replacements debe ser un dict de marcador (string no vacío) -> valor."
            )

        drive = self._get_drive_service()
        try:
            meta = (
                drive.files()
                .get(fileId=template_id, fields="mimeType", supportsAllDrives=True)
                .execute(num_retries=1)
            )
            if meta.get("mimeType") != _DOC_MIME:
                raise DocsWorkspaceDataError(
                    f"La plantilla {template_id} no es un documento de Google Docs "
                    f"(tipo {meta.get('mimeType')})."
                )
            body: dict[str, Any] = {"name": title}
            if parent_folder_id:
                body["parents"] = [parent_folder_id]
            copy = (
                drive.files()
                .copy(fileId=template_id, body=body, fields="id, name", supportsAllDrives=True)
                .execute(num_retries=1)
            )
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            raise _wrap_http_error(exc) from exc

        document_id = copy["id"]
        changed: dict[str, int] = {}
        if replacements:
            markers = list(replacements)
            try:
                result = self._get_service().documents().batchUpdate(
                    documentId=document_id,
                    body={
                        "requests": [
                            {
                                "replaceAllText": {
                                    "containsText": {"text": marker, "matchCase": True},
                                    "replaceText": str(replacements[marker]),
                                }
                            }
                            for marker in markers
                        ]
                    },
                ).execute(num_retries=1)
            except HttpError as exc:
                raise DocsWorkspaceDataError(
                    f"Se creó la copia {document_id} pero falló el reemplazo de "
                    f"variables: {_wrap_http_error(exc)}"
                ) from exc
            for marker, reply in zip(markers, result.get("replies", [])):
                changed[marker] = reply.get("replaceAllText", {}).get("occurrencesChanged", 0)

        self._logger.info(
            "Documento '%s' creado desde la plantilla %s (id=%s, usuario %s)",
            title, template_id, document_id, self.user_email,
        )
        return {
            "id": document_id,
            "title": copy.get("name", title),
            "url": f"https://docs.google.com/document/d/{document_id}/edit",
            "template_id": template_id,
            "replacements": changed,
        }

    # ------------------------------------------------------------------ #
    # Capacidad 6 — Exportar a PDF
    # ------------------------------------------------------------------ #

    def export_pdf(self, document_id: str, destination_path: str) -> str:
        """Exporta un documento a PDF y lo guarda en disco local.

        Google limita la exportación a 10 MB por archivo.

        Args:
            document_id: ID del documento.
            destination_path: ruta local del PDF. Si ya existe, se sobrescribe.

        Returns:
            La ruta local donde quedó guardado el PDF.

        Ejemplo:
            >>> client.export_pdf("1AbC...xyz", "/tmp/contrato.pdf")
            '/tmp/contrato.pdf'
        """
        document_id = _validate_document_id(document_id)
        if not destination_path:
            raise DocsWorkspaceDataError("destination_path no puede estar vacío.")
        drive = self._get_drive_service()
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            request = drive.files().export_media(fileId=document_id, mimeType="application/pdf")
            with dest.open("wb") as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=1)
        except (RefreshError, GoogleAuthError) as exc:
            raise DocsWorkspaceAuthError(
                f"No se pudo autenticar: el token OAuth/credenciales pueden "
                f"estar revocados, vencidos o ser inválidos. Vuelve a "
                f"autorizar el conector. Detalle: {exc}"
            ) from exc
        except HttpError as exc:
            dest.unlink(missing_ok=True)
            raise _wrap_http_error(exc) from exc
        self._logger.info("Documento %s exportado a PDF en %s", document_id, dest)
        return str(dest)
