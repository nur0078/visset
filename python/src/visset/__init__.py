"""visset: step-by-step visual explanations of code."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._version import __version__

if TYPE_CHECKING:
    from .tracer.request import Limits

__all__ = ["__version__", "show", "to_html", "trace"]


def trace(
    source: str,
    *,
    path: str = "main.py",
    function: str | None = None,
    args: str | tuple[Any, ...] = "",
    limits: Limits | None = None,
    sandbox: bool = True,
    title: str | None = None,
) -> dict[str, Any]:
    """Run `source` and return a visset trace (a JSON-ready dict).

    `function` traces only that function, called with `args` (Python literals as a string, or
    a tuple of literal values). `sandbox=False` runs in this process: faster to start, but no
    time or memory protection, so use it only for code you trust to finish.
    """
    from .tracer import Limits, TraceRequest, execute, run_sandboxed

    if isinstance(args, tuple):
        args = ", ".join(repr(a) for a in args)
    req = TraceRequest(
        source=source,
        path=path,
        function=function,
        args=args,
        limits=limits or Limits(),
        title=title,
    )
    result, _status = run_sandboxed(req) if sandbox else execute(req)
    return result


def to_html(trace: dict[str, Any], path: str | None = None) -> str:
    """Render a trace as one self-contained HTML file. Returns the HTML; writes it if `path`."""
    from .export.html import render_html

    html = render_html(trace)
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def show(trace: dict[str, Any]) -> str:
    """Open a trace in the browser (like `plt.show()`). Returns the file path."""
    from .export.html import open_in_browser

    return open_in_browser(trace)
