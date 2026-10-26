"""visset: step-by-step visual explanations of code.

import visset
visset.show(binary_search, [1, 3, 5, 7], 5)        # a live call, like plt.show()
                                                   # (in a notebook, it plays inline)
visset.show("total = 0\\nfor x in xs:\\n    total += x", given={"xs": [4, 5]})
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ._version import __version__

if TYPE_CHECKING:
    from .tracer.request import Limits

__all__ = ["__version__", "show", "to_html", "trace", "trace_call", "trace_source"]

Trace = dict[str, Any]


def trace(target: str | Callable[..., Any], /, *args: Any, **kwargs: Any) -> Trace:
    """Trace a function call or a piece of source code.

    - `trace(fn, *args, **kwargs)` calls `fn` and records only that call.
      (Use `trace_call` for options such as `lines=` or `limits=`.)
    - `trace("source", **options)` runs source text; see `trace_source` for the options.
    """
    if callable(target):
        return trace_call(target, args, kwargs)
    if args:
        raise TypeError("trace(source, ...) takes options as keywords; see trace_source()")
    return trace_source(target, **kwargs)


def trace_call(
    fn: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    *,
    lines: tuple[int, int] | None = None,
    limits: Limits | None = None,
    title: str | None = None,
) -> Trace:
    """Trace one call of `fn` in this process. Shows only `fn`'s source (or `lines` of its file).

    Arguments can be any objects. Runs without the sandbox, so use it on code you trust to
    finish; the step and recursion limits still apply.
    """
    from .tracer.live import trace_call as _trace_call

    return _trace_call(fn, args, kwargs, lines=lines, limits=limits, title=title)


def trace_source(
    source: str,
    *,
    path: str = "snippet.py",
    function: str | None = None,
    args: str | tuple[Any, ...] = "",
    given: str | dict[str, Any] | None = None,
    lines: tuple[int, int] | None = None,
    stdin: str = "",
    limits: Limits | None = None,
    sandbox: bool = True,
    title: str | None = None,
) -> Trace:
    """Run source text and record it.

    - `given`: inputs for a snippet, e.g. `{"arr": [1, 3, 5], "target": 3}` (literals).
    - `function` + `args`: run the module untraced, then trace only that call.
    - `lines`: show only these lines (1-based, inclusive), e.g. part of a function.
    - `sandbox=False`: run in this process (faster start, no time/memory protection).
    """
    import textwrap

    from .tracer import Limits, TraceRequest, execute, run_sandboxed

    if isinstance(args, tuple):
        args = ", ".join(repr(a) for a in args)
    if isinstance(given, dict):
        given = ", ".join(f"{k}={v!r}" for k, v in given.items())
    req = TraceRequest(
        source=textwrap.dedent(source),  # a pasted fragment of a function is indented
        path=path,
        function=function,
        args=args,
        given=given or "",
        lines=lines,
        stdin=stdin,
        limits=limits or Limits(),
        title=title,
    )
    result, _status = run_sandboxed(req) if sandbox else execute(req)
    return result


def to_html(trace: Trace, path: str | None = None) -> str:
    """Render a trace as one self-contained HTML file. Returns the HTML; writes it if `path`.

    In a notebook, the returned string displays as the player rather than as raw HTML.
    """
    from .export.html import NotebookHTML, render_html

    html = NotebookHTML(render_html(trace), trace)
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def show(target: Trace | str | Callable[..., Any], /, *args: Any, **kwargs: Any) -> str | None:
    """Show a walkthrough, like `plt.show()`.

    In a notebook (Jupyter, JupyterLab, VS Code, Colab) the player appears under the cell and
    this returns None. Elsewhere it opens in the browser and returns the HTML file's path.

    Accepts a trace, or the same arguments as `trace()`: `show(fn, *args)` / `show("code")`.
    """
    from .export.html import display_inline, in_notebook, open_in_browser

    data = target if isinstance(target, dict) else trace(target, *args, **kwargs)
    if in_notebook():
        display_inline(data)
        return None
    return open_in_browser(data)
