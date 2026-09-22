"""MCP server for Adobe Illustrator (Windows, COM + ExtendScript).

Built for Illustrator 2020 (v24) but uses only APIs available since CS6.
Works with any MCP client that supports local stdio servers (Codex, Claude Desktop, Claude Code).
"""

import json
import os
import sys
import tempfile
import uuid

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

PROGID = os.environ.get("ILLUSTRATOR_PROGID", "Illustrator.Application")
ERR = "__ERR__|"

server = MCPServer(
    name="illustrator",
    instructions=(
        "Controls a running Adobe Illustrator. Scripts are ExtendScript (ES3): no let/const, "
        "no arrow functions, no template strings, no JSON object. Always render_artboard after "
        "changes to check the result visually."
    ),
)


def js(value: object) -> str:
    """Python value -> ES3 literal (json.dumps with ensure_ascii is valid ES3)."""
    return json.dumps(value)


def wrap(body: str) -> str:
    """Wrap a function body so errors come back as text and no modal dialog can block COM."""
    return (
        "(function(){\n"
        "var __lvl = app.userInteractionLevel;\n"
        "app.userInteractionLevel = UserInteractionLevel.DONTDISPLAYALERTS;\n"
        "try {\n"
        "var __r = (function(){\n" + body + "\n})();\n"
        "return (__r === undefined || __r === null) ? '' : String(__r);\n"
        "} catch (e) {\n"
        f"return {js(ERR)} + e + ' (line ' + e.line + ')';\n"
        "} finally {\n"
        "app.userInteractionLevel = __lvl;\n"
        "}\n"
        "})();\n"
    )


def run_jsx_raw(body: str) -> str:
    """Execute an ExtendScript function body in Illustrator via COM. Raises on script error."""
    if sys.platform != "win32":
        raise ToolError("Illustrator COM automation only works on Windows.")
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()  # tools may run on worker threads
    path = os.path.join(tempfile.gettempdir(), f"ai-mcp-{uuid.uuid4().hex}.jsx")
    # ExtendScript reads UTF-8 reliably only with BOM
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(wrap(body))
    try:
        app = win32com.client.Dispatch(PROGID)
        result = app.DoJavaScriptFile(path)
    except pythoncom.com_error as exc:
        raise ToolError(f"Cannot talk to Illustrator via COM ({PROGID}): {exc}") from exc
    finally:
        os.unlink(path)
    result = "" if result is None else str(result)
    if result.startswith(ERR):
        raise ToolError(f"ExtendScript error: {result[len(ERR):]}")
    return result


# --- ExtendScript recipes (pure string builders, testable without Illustrator) ---

INFO_JSX = """
var out = ['Illustrator ' + app.version, 'documents: ' + app.documents.length];
if (app.documents.length) {
  var d = app.activeDocument;
  out.push('active: ' + d.name + ' (' + (d.documentColorSpace == DocumentColorSpace.CMYK ? 'CMYK' : 'RGB') + ')');
  out.push('artboards: ' + d.artboards.length + ', paths: ' + d.pathItems.length + ', compound paths: ' + d.compoundPathItems.length);
  for (var i = 0; i < d.artboards.length; i++) {
    var r = d.artboards[i].artboardRect;
    out.push('  [' + i + '] ' + d.artboards[i].name + ' ' + Math.round(r[2] - r[0]) + 'x' + Math.round(r[1] - r[3]) + ' pt');
  }
}
return out.join('\\n');
"""


def render_jsx(png_path: str, artboard: int, max_px: int) -> str:
    return f"""
var d = app.activeDocument;
d.artboards.setActiveArtboardIndex({artboard});
var r = d.artboards[{artboard}].artboardRect;
var side = Math.max(r[2] - r[0], r[1] - r[3]);
var scale = Math.min(776, Math.max(1, 100 * {max_px} / side));
var o = new ExportOptionsPNG24();
o.artBoardClipping = true; o.antiAliasing = true; o.transparency = false;
o.horizontalScale = scale; o.verticalScale = scale;
d.exportFile(new File({js(png_path)}), ExportType.PNG24, o);
return 'ok';
"""


def vectorize_jsx(
    image_path: str,
    colors: int,
    threshold: int,
    path_fidelity: int,
    corner_fidelity: int,
    noise: int,
    ignore_white: bool,
) -> str:
    return f"""
var f = new File({js(image_path)});
if (!f.exists) throw new Error('image not found: ' + f.fsName);
var d = app.documents.add(DocumentColorSpace.CMYK);
var placed = d.placedItems.add();
placed.file = f;
placed.position = [0, 0];
var b = placed.geometricBounds;
d.artboards[0].artboardRect = [b[0], b[1], b[2], b[3]];
var plugin = placed.trace();
var o = plugin.tracing.tracingOptions;
var skipped = [];
function set(name, value) {{ try {{ o[name] = value; }} catch (e) {{ skipped.push(name); }} }}
if ({colors} <= 1) {{
  set('tracingMode', TracingModeType.TRACINGMODEBLACKANDWHITE);
  set('threshold', {threshold});
}} else {{
  set('tracingMode', TracingModeType.TRACINGMODECOLOR);
  set('tracingColorTypeValue', TracingColorType.TRACINGLIMITEDCOLOR);
  set('maxColors', {colors});
}}
set('fills', true); set('strokes', false);
set('pathFidelity', {path_fidelity}); set('cornerFidelity', {corner_fidelity}); set('noiseFidelity', {noise});
set('ignoreWhite', {js(ignore_white)});
app.redraw();
var group = plugin.tracing.expandTracing();
return 'traced: ' + d.pathItems.length + ' paths, ' + d.compoundPathItems.length + ' compound paths' +
  (skipped.length ? ' | unsupported options: ' + skipped.join(', ') : '');
"""


def ink_jsx(c: float, m: float, y: float, k: float, selection_only: bool) -> str:
    return f"""
var d = app.activeDocument;
var ink = new CMYKColor(); ink.cyan = {c}; ink.magenta = {m}; ink.yellow = {y}; ink.black = {k};
var items = {js(selection_only)} ? d.selection : d.pathItems;
var n = 0;
function paint(it) {{
  if (it.typename == 'PathItem') {{ if (it.filled) {{ it.fillColor = ink; n++; }} }}
  else if (it.typename == 'CompoundPathItem') {{ for (var j = 0; j < it.pathItems.length; j++) paint(it.pathItems[j]); }}
  else if (it.typename == 'GroupItem') {{ for (var g = 0; g < it.pageItems.length; g++) paint(it.pageItems[g]); }}
}}
for (var i = 0; i < items.length; i++) paint(items[i]);
return 'recoloured fills: ' + n;
"""


def export_jsx(out_path: str, kind: str, pdf_preset: str) -> str:
    if kind == "pdf":
        return f"""
var o = new PDFSaveOptions();
o.pDFPreset = {js(pdf_preset)};
app.activeDocument.saveAs(new File({js(out_path)}), o);
return 'saved ' + {js(out_path)};
"""
    return f"""
var o = new ExportOptionsSVG();
o.embedRasterImages = false;
o.fontType = SVGFontType.OUTLINEFONT;
app.activeDocument.exportFile(new File({js(out_path)}), ExportType.SVG, o);
return 'exported ' + {js(out_path)};
"""


# --- MCP tools ---


@server.tool()
def illustrator_info() -> str:
    """Illustrator version, open documents and artboards of the active document."""
    return run_jsx_raw(INFO_JSX)


@server.tool()
def run_jsx(code: str) -> str:
    """Run an ExtendScript (ES3) function body in Illustrator. Use `return` to send a value back.
    Example: `return app.activeDocument.pathItems.length;`"""
    return run_jsx_raw(code)


@server.tool()
def render_artboard(artboard: int = 0, max_px: int = 1024) -> list:
    """Render an artboard of the active document to PNG (only the document, never the screen).
    Returns the image plus the saved file path."""
    png = os.path.join(tempfile.gettempdir(), f"ai-render-{uuid.uuid4().hex[:8]}.png")
    run_jsx_raw(render_jsx(png, artboard, max_px))
    return [Image(path=png), f"saved: {png}"]


@server.tool()
def vectorize_image(
    image_path: str,
    colors: int = 1,
    threshold: int = 128,
    path_fidelity: int = 70,
    corner_fidelity: int = 75,
    noise: int = 8,
    ignore_white: bool = True,
) -> str:
    """Open a raster image in a new CMYK document, Image Trace it and expand to editable paths.
    colors=1 -> black & white trace (use for one-ink logos); colors>1 -> limited colour trace.
    Lower noise keeps finer detail; higher path_fidelity follows the pixels more closely."""
    return run_jsx_raw(
        vectorize_jsx(image_path, colors, threshold, path_fidelity, corner_fidelity, noise, ignore_white)
    )


@server.tool()
def set_ink_cmyk(
    cyan: float, magenta: float, yellow: float, black: float, selection_only: bool = False
) -> str:
    """Set the fill of every filled path (or only the selection) to one CMYK ink, values 0-100."""
    for v in (cyan, magenta, yellow, black):
        if not 0 <= v <= 100:
            raise ToolError("CMYK values must be between 0 and 100")
    return run_jsx_raw(ink_jsx(cyan, magenta, yellow, black, selection_only))


@server.tool()
def export_document(output_path: str, kind: str = "pdf", pdf_preset: str = "[PDF/X-4:2008]") -> str:
    """Export the active document. kind='pdf' saves with a PDF preset (default PDF/X-4),
    kind='svg' exports SVG with text as outlines."""
    if kind not in ("pdf", "svg"):
        raise ToolError("kind must be 'pdf' or 'svg'")
    return run_jsx_raw(export_jsx(output_path, kind, pdf_preset))


if __name__ == "__main__":
    server.run()
