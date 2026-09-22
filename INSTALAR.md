# Illustrator MCP — instalación en Windows 11 + Codex

Conecta Codex (o cualquier cliente MCP local) con Adobe Illustrator 2020 o posterior.
Todo corre en el propio PC: no abre puertos ni envía nada fuera salvo lo que haga Codex.

## 1. Python

PowerShell:

```powershell
winget install Python.Python.3.12
```

Cerrar y abrir PowerShell para que `py` quede en el PATH.

## 2. Copiar y preparar la carpeta

Copiar `illustrator_mcp.py` a `C:\Herramientas\illustrator-mcp\` y en PowerShell:

```powershell
cd C:\Herramientas\illustrator-mcp
py -3.12 -m venv .venv
.venv\Scripts\pip install "mcp>=2.2,<3" pywin32
```

## 3. Registrar en Codex

Editar `%USERPROFILE%\.codex\config.toml` (crearlo si no existe) y añadir:

```toml
[mcp_servers.illustrator]
command = 'C:\Herramientas\illustrator-mcp\.venv\Scripts\python.exe'
args = ['C:\Herramientas\illustrator-mcp\illustrator_mcp.py']
tool_timeout_sec = 300
```

Comillas simples a propósito: así las `\` no necesitan escaparse.

Reiniciar Codex.

## 4. Primera prueba

1. Abrir Illustrator (normal, **no** como administrador: si uno va elevado y el otro no, COM falla).
2. En Codex: *"Usa illustrator_info"* → debe responder `Illustrator 24.x`.
3. *"Vectoriza C:\Users\Amalia\Desktop\logo.png a una tinta, ponlo en CMYK 100/80/0/40,
   enséñame cómo queda y expórtalo a PDF/X-4 en el Escritorio."*

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `illustrator_info` | Versión, documentos abiertos, mesas de trabajo |
| `vectorize_image` | Abre una imagen en documento CMYK nuevo, calco de imagen y expandir |
| `set_ink_cmyk` | Pone todos los rellenos (o la selección) a una tinta CMYK |
| `render_artboard` | PNG de la mesa de trabajo para que el modelo vea el resultado (solo el documento, nunca la pantalla) |
| `export_document` | PDF con ajuste preestablecido (PDF/X-4 por defecto) o SVG |
| `run_jsx` | Cualquier script ExtendScript para lo que no cubren las anteriores |

## Problemas conocidos

- **`Cannot talk to Illustrator via COM ... Invalid class string`**: añadir en el bloque de Codex
  `env = { ILLUSTRATOR_PROGID = "Illustrator.Application.24" }`.
- **El PDF falla por el nombre del ajuste**: pedir a Codex *"lista app.PDFPresetsList con run_jsx"* y usar
  el nombre exacto que salga (en Illustrator en español algunos nombres van traducidos).
- **`unsupported options: ...` al vectorizar**: esa opción no existe en esta versión; el calco se hace igualmente.
- **Illustrator parece colgado**: los scripts desactivan los diálogos, pero si hay uno abierto a mano
  (p. ej. "Guardar cambios") cerrarlo antes de pedir nada.
