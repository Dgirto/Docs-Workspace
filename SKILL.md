---
name: docs-workspace
description: >
  Usa la librería ruvic_docs_workspace_connector para leer, crear y
  editar documentos accesibles por uno o varios usuarios de un dominio
  Google Workspace, vía cuenta de servicio con delegación de dominio
  (impersonación) - leer el título y texto completo de un documento
  (read_document), crear un documento nuevo (create_document), agregar
  texto al final (append_text) y buscar/reemplazar texto en todo el
  documento (replace_text). Úsala cuando el usuario pida leer, resumir,
  crear, redactar o actualizar un documento de Google Docs en un
  contexto de Google Workspace, especialmente si menciona varios
  usuarios del mismo dominio sin volver a autorizar cada uno por
  separado. Para una cuenta personal o un solo usuario autorizado
  individualmente, usa en su lugar el conector `docs` (OAuth2).
triggers:
- google docs
- documento
- documentos
- docs
- acta
- plantilla
- redactar documento
- crear documento
- workspace
- delegación de dominio
---

# Conector Google Docs Workspace (ruvic_docs_workspace_connector)

Librería Python para leer, crear y editar documentos accesibles por usuarios de un dominio **Google Workspace**, usando una **cuenta de servicio con delegación de dominio**. Está **preinstalada en el runtime** cuando el conector está configurado (si no, instálala con `pip install git+https://github.com/Dgirto/Docs-Workspace.git#subdirectory=lib`).

## Cuándo usar este conector vs. el de OAuth2

Ruvic tiene dos conectores de Docs; elige según el caso:

| Situación | Conector a usar |
|-----------|------------------|
| Cuenta de Google personal, o un solo usuario corporativo autorizado individualmente | `docs` (OAuth2) — ver su `SKILL.md` |
| **Google Workspace, una sola credencial para impersonar varios usuarios del dominio** (ej. `facturacion@empresa.com`, `soporte@empresa.com`), sin re-autorizar cada uno | **`docs_workspace` (este)** |

Este conector **no funciona con cuentas Gmail/Google personales** — Google no permite delegación de dominio fuera de Workspace.

## Regla crítica de credenciales

El código generado **NUNCA hardcodea credenciales**. Siempre se leen de variables de entorno, disponibles cuando el conector `docs_workspace` está configurado:

| Variable | Contenido |
|----------|-----------|
| `RUVIC_DOCS_WORKSPACE_SERVICE_ACCOUNT_JSON` | JSON completo de la cuenta de servicio de Google Cloud |
| `RUVIC_DOCS_WORKSPACE_DEFAULT_USER` | Usuario usado solo para el test de conexión |
| `RUVIC_DOCS_WORKSPACE_REQUEST_TIMEOUT` | (opcional) timeout en segundos, default 30 |

Si estas variables NO existen, el conector no está configurado: no generes código que lo use; indica al usuario que lo configure en **Settings → Conectores**. El código generado **NUNCA** usa nombres con segmento de alias (`_DEFAULT_INSTANCIA_`, `_PRODUCCION_`, etc.) salvo que aparezcan en una sección autogenerada `## Variables en tu entorno` al final de este skill.

## Autenticación / conexión (siempre igual)

El usuario a impersonar se pasa en el **constructor**, no en cada método:

```python
from ruvic_docs_workspace_connector import DocsWorkspaceClient

client = DocsWorkspaceClient(user_email="facturacion@tuempresa.com")
```

Para trabajar con varios usuarios, crea una instancia por usuario:

```python
usuarios = ["facturacion@tuempresa.com", "soporte@tuempresa.com"]
clientes = {u: DocsWorkspaceClient(user_email=u) for u in usuarios}
```

## Identificar el documento

El `document_id` es el que aparece en la URL del documento:
`https://docs.google.com/document/d/`**`ESTE_ID`**`/edit`. Si el usuario
pega la URL completa, extrae solo esa parte.

## Capacidad 1 — Leer un documento

```python
doc = client.read_document("1AbC...xyz")
print(doc["title"])
print(doc["body_text"])
```

## Capacidad 2 — Crear un documento nuevo

```python
created = client.create_document(
    "Acta de reunión — julio",
    body_text="Asistentes:\n- ...\n\nAcuerdos:\n- ...\n",  # opcional
)
print(created["url"])
```

El documento se crea en la raíz de "Mi unidad" del usuario impersonado.

## Capacidad 3 — Agregar texto al final

```python
result = client.append_text("1AbC...xyz", "\nPárrafo agregado al final.\n")
```

## Capacidad 4 — Buscar y reemplazar texto

```python
result = client.replace_text("1AbC...xyz", "{{CLIENTE}}", "ACME S.A.")
```

Reemplaza **todas** las ocurrencias (texto literal, no regex). Ideal para llenar plantillas con marcadores tipo `{{CAMPO}}`.

## Manejo de errores

```python
from ruvic_docs_workspace_connector import (
    DocsWorkspaceAuthError, DocsWorkspaceDataError, DocsWorkspaceNetworkError,
)

try:
    client.append_text("1AbC...xyz", "texto")
except DocsWorkspaceAuthError:
    print("Delegación de dominio no autorizada para este usuario — revisa el Admin Console")
except DocsWorkspaceNetworkError:
    print("Docs API no respondió — puede ser un límite de cuota temporal")
except DocsWorkspaceDataError as e:
    print(f"Error de datos: {e}")  # ej. el documento no existe o no es accesible
```

`DocsWorkspaceAuthError` incluye en su mensaje el Client ID exacto que debe estar autorizado en el Admin Console, y qué revisar (Client ID, scope, dominio del usuario) — muéstraselo tal cual al usuario cuando ocurra.

## Buenas prácticas al generar código

1. Lee credenciales SOLO de las variables `RUVIC_DOCS_WORKSPACE_*` (el constructor de `DocsWorkspaceConfig` ya lo hace).
2. Nunca imprimas `RUVIC_DOCS_WORKSPACE_SERVICE_ACCOUNT_JSON` en logs ni en la salida.
3. El `user_email` del constructor puede ser **cualquier** usuario del dominio autorizado, no solo el de prueba (`DEFAULT_USER`).
4. El conector solo puede acceder a documentos que estén **compartidos con el usuario impersonado** (o de su propiedad).
5. Para llenar plantillas, usa `replace_text` con marcadores únicos (`{{CLIENTE}}`, `{{FECHA}}`) — una llamada por marcador.
6. `read_document` devuelve texto plano sin formato — no preserva estilos, imágenes ni comentarios.
7. El conector no elimina documentos, no cambia permisos ni accede a otros archivos de Drive.
