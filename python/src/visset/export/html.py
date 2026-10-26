"""Standalone HTML export: one file with the player, its styles, and the trace inlined.

Works offline and from `file://`, so it can be emailed, committed, or dropped on any host.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import webbrowser
from functools import cache
from html import escape
from importlib import resources
from pathlib import Path
from typing import Any

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="{generator}">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
<visset-player global-keys>
<script type="application/json">{trace}</script>
</visset-player>
<script>{player}</script>
</body>
</html>
"""


_PAGE_STYLE = """
  :root { color-scheme: light dark; }
  html, body { margin: 0; height: 100%; background: #f5f5f7; }
  @media (prefers-color-scheme: dark) { html, body { background: #000; } }
  body { display: flex; justify-content: center; box-sizing: border-box; padding: 24px; }
  visset-player { width: 100%; max-width: 1280px; height: calc(100vh - 48px); min-height: 520px; }
  @media (max-width: 700px) { body { padding: 0; } visset-player { height: 100vh; } }
"""

# Inside a notebook's output frame: the player fills the frame, with no page around it.
_EMBED_STYLE = """
  :root { color-scheme: light dark; }
  html, body { margin: 0; height: 100%; background: transparent; }
  visset-player { display: block; width: 100%; height: 100%; }
"""

# Notebook output height. The player needs about this much to show code and state side by side.
NOTEBOOK_HEIGHT = 640


class PlayerMissingError(RuntimeError):
    pass


@cache
def player_js() -> str:
    try:
        return (resources.files("visset") / "_assets" / "player.js").read_text("utf-8")
    except FileNotFoundError as e:
        raise PlayerMissingError(
            "the player bundle is missing (visset/_assets/player.js). In a source checkout, "
            "build it with: pnpm install && pnpm build"
        ) from e


def _json_for_script(trace: dict[str, Any]) -> str:
    # Inside <script>, the only dangerous sequence is "</script" (and "<!--"). In JSON, "<"
    # can only appear inside strings, where the escape < means the same character.
    text = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c")


def render_html(trace: dict[str, Any], *, embed: bool = False) -> str:
    """The standalone page. `embed=True` drops the page padding, for display inside a frame."""
    meta = trace.get("meta", {})
    title = str(meta.get("title") or "walkthrough")
    # The player is plain JS: never let "</script" inside it end the tag early.
    js = player_js().replace("</script", "<\\/script")
    return _PAGE.format(
        title=escape(f"{title} · visset"),
        generator=escape(str(meta.get("generator", "visset"))),
        style=_EMBED_STYLE if embed else _PAGE_STYLE,
        trace=_json_for_script(trace),
        player=js,
    )


def render_notebook(trace: dict[str, Any], height: int = NOTEBOOK_HEIGHT) -> str:
    """HTML for a notebook output cell: the page inside an iframe.

    The frame keeps the player's script, styles, and keyboard shortcuts out of the notebook's own
    page, and lets the same trace be shown in many cells (the custom element is defined once per
    frame). Works in Jupyter, JupyterLab, VS Code, and Colab, which all run scripts in an
    `srcdoc` frame.
    """
    page = render_html(trace, embed=True)
    title = escape(str(trace.get("meta", {}).get("title") or "walkthrough"))
    return (
        f'<iframe srcdoc="{escape(page, quote=True)}" title="{title} · visset" '
        f'style="width: 100%; height: {int(height)}px; border: 0; display: block;" '
        'allow="clipboard-write"></iframe>'
    )


class NotebookHTML(str):
    """The standalone page as a string, which a notebook shows as the player instead of text."""

    _trace: dict[str, Any]

    def __new__(cls, page: str, trace: dict[str, Any]) -> NotebookHTML:
        self = super().__new__(cls, page)
        self._trace = trace
        return self

    def _repr_mimebundle_(self, include: Any = None, exclude: Any = None) -> dict[str, str]:
        return notebook_bundle(self._trace)


def in_notebook() -> bool:
    """True when running in a Jupyter-style kernel (Jupyter, JupyterLab, VS Code, Colab)."""
    import sys

    if "IPython" not in sys.modules:
        return False
    from IPython import get_ipython

    shell = get_ipython()
    return shell is not None and "IPKernelApp" in shell.config


def notebook_bundle(trace: dict[str, Any], height: int = NOTEBOOK_HEIGHT) -> dict[str, str]:
    """What a notebook shows: the player, or a one-line summary where HTML can't render."""
    title = str(trace.get("meta", {}).get("title") or "walkthrough")
    return {
        "text/html": render_notebook(trace, height),
        "text/plain": f"<visset walkthrough: {title}>",
    }


def display_inline(trace: dict[str, Any], height: int = NOTEBOOK_HEIGHT) -> None:
    from IPython.display import display

    display(notebook_bundle(trace, height), raw=True)


def open_in_browser(trace: dict[str, Any], path: str | None = None) -> str:
    html = render_html(trace)
    if path is None:
        digest = hashlib.sha1(html.encode("utf-8")).hexdigest()[:10]
        name = str(trace.get("meta", {}).get("title") or "trace")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40]
        folder = Path(tempfile.gettempdir()) / "visset"
        folder.mkdir(exist_ok=True)
        path = str(folder / f"{safe}-{digest}.html")
    Path(path).write_text(html, encoding="utf-8")
    webbrowser.open(Path(path).resolve().as_uri())
    return path
