# Conector Google Docs Workspace (CON-008.1)

Conector Ruvic para Google Docs en un dominio **Google Workspace**, vía
**cuenta de servicio con delegación de dominio**. Una sola credencial
puede impersonar a cualquier usuario autorizado del dominio y leer/
crear/editar los documentos a los que ese usuario tenga acceso
(`facturacion@empresa.com`, `soporte@empresa.com`, …) sin re-autorizar
cada uno individualmente y sin tokens que expiren.

Es el segundo conector Docs del catálogo — ver [CON-008](../CON-008)
(OAuth2, un usuario por autorización). Usa el mismo patrón de
autenticación que [CON-005.2](../CON-005.2) (Gmail Workspace),
[CON-007](../CON-007) (Drive Workspace) y [CON-006.1](../CON-006.1)
(Sheets Workspace) — si ya tienes esa cuenta de servicio configurada,
puedes reutilizarla agregando el scope de Docs a la misma entrada de
delegación en el Admin Console.

**Solo funciona con Google Workspace** — Google no permite delegación
de dominio en cuentas Google personales.

## Instalación

```bash
pip install git+https://github.com/Dgirto/Docs-Workspace.git#subdirectory=lib
```

Python 3.10+. Dependencias: `google-auth` y `google-api-python-client`.

## Obtener credenciales (una sola vez, por dominio Workspace)

### 1. Proyecto y cuenta de servicio en Google Cloud Console

1. Crea (o reutiliza) un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Habilita la **Google Docs API**.
3. Ve a **IAM y administración → Cuentas de servicio → Crear cuenta de servicio**. Dale un nombre (ej. `ruvic-docs-workspace`) y termina el asistente sin roles adicionales de proyecto. (Si ya tienes la cuenta de servicio de CON-005.2, CON-006.1 o CON-007, puedes reutilizarla.)
4. Abre la cuenta de servicio → pestaña **Claves** → **Agregar clave → Crear clave nueva → JSON**. Se descarga un archivo `.json` — este es el que va al formulario del conector.
5. En la pestaña **Detalles**, copia el **ID de cliente único**.

### 2. Delegación de dominio (solo el superadministrador de Workspace puede hacer esto)

1. El superadministrador entra a [admin.google.com](https://admin.google.com/) → **Seguridad → Control de acceso a las API → Delegación en todo el dominio**.
2. Si el Client ID ya está agregado (ej. porque ya configuraste Gmail, Sheets o Drive Workspace), edita esa misma entrada y agrega los scopes de Docs y Drive a la lista. Si no, clic en **Agregar nuevo**.
3. **ID de cliente**: el ID de cliente único del paso anterior.
4. **Alcances OAuth**:
   ```
   https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/drive
   ```
   `drive` es necesario para `create_from_template` (copiar la plantilla) y
   `export_pdf`. Si la delegación ya existía solo con `documents`, agrega
   `drive` a la misma entrada.
5. Guardar.

> Sin este paso, cualquier intento de conexión falla con `unauthorized_client` — el conector detecta este error específico y explica exactamente qué revisar.

## Variables de entorno (`RUVIC_DOCS_WORKSPACE_*`)

| Variable | Obligatoria | Descripción |
|----------|-------------|-------------|
| `RUVIC_DOCS_WORKSPACE_SERVICE_ACCOUNT_JSON` | Sí | JSON completo de la cuenta de servicio |
| `RUVIC_DOCS_WORKSPACE_DEFAULT_USER` | Sí | Usuario del dominio usado para el botón "Probar conexión" |
| `RUVIC_DOCS_WORKSPACE_REQUEST_TIMEOUT` | No (default `30`) | Timeout de solicitud en segundos |

## Pruebas locales

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ./lib

export RUVIC_DOCS_WORKSPACE_SERVICE_ACCOUNT_JSON='{"type": "service_account", ...}'
export RUVIC_DOCS_WORKSPACE_DEFAULT_USER=facturacion@tudominio.com

python test_connection.py
python validate_local.py
```

`validate_local.py` no necesita ningún documento previo: crea uno
nuevo en el Drive del usuario impersonado, le agrega texto, reemplaza
un marcador de plantilla y lo vuelve a leer completo.

Prueba también los casos de error (delegación no configurada — el más
importante y el que da `unauthorized_client`, cuenta de servicio con
clave inválida, documento inexistente) y verifica que los mensajes
sean claros.

## Notas de integración

- **Mismo patrón que CON-005.2, CON-006.1 y CON-007**: mismo
  constructor (`user_email`), misma clasificación de errores
  (Auth/Network/Data), mismo manejo explícito de `unauthorized_client`.
- **Una credencial, N usuarios**: `DocsWorkspaceClient(user_email="...")`
  acepta cualquier usuario autorizado del dominio, no solo el
  `DEFAULT_USER` de prueba.
- **Sin expiración de tokens**: la delegación de dominio no genera un
  `refresh_token` que pueda vencer — el acceso dura mientras la
  delegación siga activa en el Admin Console.
- **Detección de API deshabilitada**: si la Docs API no está habilitada
  en el proyecto de Cloud, el error indica la API exacta y el enlace
  directo de activación (caso `SERVICE_DISABLED`).
- **Revocación**: para revocar el acceso, el superadministrador elimina
  o edita la entrada de delegación en el Admin Console, o se
  elimina/rota la clave de la cuenta de servicio en Google Cloud Console.
- Los errores HTTP 401/403 de la API se clasifican como
  `DocsWorkspaceAuthError`; 404 como `DocsWorkspaceDataError`; 429 y
  5xx como `DocsWorkspaceNetworkError` (reintentable).

## Limitaciones conocidas

- Solo puede acceder a documentos **compartidos con el usuario
  impersonado** (o de su propiedad) — no puede descubrir ni listar
  documentos por sí solo.
- `read_document` devuelve **texto plano**: no preserva estilos,
  imágenes, encabezados/pies de página ni comentarios.
- `replace_text` busca texto **literal** (no expresiones regulares) y
  reemplaza todas las ocurrencias.
- No elimina documentos, no cambia permisos ni mueve archivos entre
  carpetas. Solo exporta a PDF (límite de Google: 10 MB por documento).
- `create_from_template` copia la plantilla y reemplaza los marcadores
  solo en la copia; la plantilla nunca se modifica.
- La delegación aplica a **todo el dominio**: la cuenta de servicio
  puede impersonar a cualquier usuario autorizado, incluidos los que
  se creen en el futuro. No hay forma de restringirla a una lista
  específica de usuarios desde el Admin Console.
- Requiere que un superadministrador del dominio haga el paso de
  delegación — no es autoservicio para el usuario final del conector.
