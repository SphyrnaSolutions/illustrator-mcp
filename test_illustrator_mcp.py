"""Checks runnable without Illustrator: JSX syntax (node --check), ES3 compliance, tool wiring.

Run: python test_illustrator_mcp.py
"""

import asyncio
import re
import shutil
import subprocess
import tempfile

from mcp.server.mcpserver.exceptions import ToolError

import illustrator_mcp as m

RECIPES = {
    "info": m.INFO_JSX,
    "render": m.render_jsx("C:\\Temp\\a b\\ñ.png", 0, 1024),
    "vectorize_bw": m.vectorize_jsx(
        'C:\\Users\\Amalia\\Escritorio\\logo "final".png', 1, 128, 70, 75, 8, True
    ),
    "vectorize_color": m.vectorize_jsx("C:\\x.png", 3, 128, 70, 75, 8, False),
    "ink": m.ink_jsx(100, 80, 0, 40, False),
    "export_pdf": m.export_jsx("C:\\out\\logo.pdf", "pdf", "[PDF/X-4:2008]"),
    "export_svg": m.export_jsx("C:\\out\\logo.svg", "svg", ""),
}
ES_NEWER = re.compile(r"=>|\blet\s|\bconst\s|`|\bJSON\.|\.forEach\(|\.map\(")


def check_jsx_syntax_and_es3():
    node = shutil.which("node")
    assert node, "node is required for the syntax check"
    for name, body in RECIPES.items():
        src = m.wrap(body)
        assert not ES_NEWER.search(src), f"{name}: non-ES3 construct {ES_NEWER.search(src).group()!r}"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(src)
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True, check=False)
        assert r.returncode == 0, f"{name}: syntax error\n{r.stderr}"


def check_paths_are_escaped():
    body = RECIPES["vectorize_bw"]
    assert '"C:\\\\Users\\\\Amalia\\\\Escritorio\\\\logo \\"final\\".png"' in body
    assert "\\u00f1" in RECIPES["render"]  # non-ASCII escaped, safe for ExtendScript


def check_tools_with_fake_illustrator():
    calls = []

    def fake(body):
        calls.append(body)
        if "BOOM" in body:
            raise ToolError("ExtendScript error: boom (line 3)")
        return "ok"

    m.run_jsx_raw_real = m.run_jsx_raw
    m.run_jsx_raw = fake

    async def go():
        names = {t.name for t in await m.server.list_tools()}
        assert names == {
            "illustrator_info",
            "run_jsx",
            "render_artboard",
            "vectorize_image",
            "set_ink_cmyk",
            "export_document",
        }, names
        ok = await m.server.call_tool("run_jsx", {"code": "return 1;"})
        assert "ok" in str(ok), ok
        for name, args, needle in [
            ("run_jsx", {"code": "BOOM"}, "boom (line 3)"),
            ("set_ink_cmyk", {"cyan": 120, "magenta": 0, "yellow": 0, "black": 0}, "between 0 and 100"),
            ("export_document", {"output_path": "x", "kind": "png"}, "pdf' or 'svg"),
        ]:
            try:
                await m.server.call_tool(name, args)
            except ToolError as e:  # ToolError text reaches the model; other exceptions are hidden
                assert needle in str(e), (name, e)
            else:
                raise AssertionError(f"{name} should fail")

    asyncio.run(go())
    assert calls == ["return 1;", "BOOM"], calls  # invalid CMYK / kind never reach Illustrator


def check_non_windows_refuses():
    try:
        m.run_jsx_raw_real("return 1;")
    except ToolError as e:
        assert "Windows" in str(e)
    else:
        raise AssertionError("should refuse outside Windows")


if __name__ == "__main__":
    check_jsx_syntax_and_es3()
    check_paths_are_escaped()
    check_tools_with_fake_illustrator()
    check_non_windows_refuses()
    print("all checks passed")
