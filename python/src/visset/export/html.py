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
<style>
  :root {{ color-scheme: light dark; }}
  html, body {{ margin: 0; height: 100%; background: #f5f5f7; }}
  @media (prefers-color-scheme: dark) {{ html, body {{ background: #000; }} }}
  body {{ display: flex; justify-content: center; box-sizing: border-box; padding: 24px; }}
  visset-player {{ width: 100%; max-width: 1280px; height: calc(100vh - 48px); min-height: 520px; }}
  @media (max-width: 700px) {{ body {{ padding: 0; }} visset-player {{ height: 100vh; }} }}
</style>
</head>
<body>
<visset-player global-keys>
<script type="application/json">{trace}</script>
</visset-player>
<script>{player}</script>
</body>
</html>
"""


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


def render_html(trace: dict[str, Any]) -> str:
    meta = trace.get("meta", {})
    title = str(meta.get("title") or "walkthrough")
    # The player is plain JS: never let "</script" inside it end the tag early.
    js = player_js().replace("</script", "<\\/script")
    return _PAGE.format(
        title=escape(f"{title} · visset"),
        generator=escape(str(meta.get("generator", "visset"))),
        trace=_json_for_script(trace),
        player=js,
    )


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
