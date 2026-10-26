"""Trace a live function call in this process: `visset.show(binary_search, [1, 3, 5], 3)`.

Arguments can be any Python objects (not just literals), which is why this path can't use the
sandboxed child process: live objects don't cross a process boundary. Use it for code you trust
to finish; the step and recursion limits still apply.
"""

from __future__ import annotations

import inspect
import linecache
import reprlib
from collections.abc import Callable
from typing import Any

from .engine import Capture, Tracer
from .positions import SourceIndex
from .request import Limits, TraceRequest
from .run import TraceError, finish_trace, run_body


def trace_call(
    fn: Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    *,
    lines: tuple[int, int] | None = None,
    limits: Limits | None = None,
    title: str | None = None,
    stdin: str = "",
) -> dict[str, Any]:
    func = inspect.unwrap(fn)
    if inspect.ismethod(func):
        func = func.__func__
    code = getattr(func, "__code__", None)
    if code is None:
        raise TraceError(f"{fn!r} is not a Python function, so there is no source to step through")
    filename = code.co_filename
    source = "".join(linecache.getlines(filename))
    if not source:
        raise TraceError(
            f"can't find the source of {func.__qualname__} (defined in {filename!r}). "
            "Functions typed into stdin or some REPLs keep no source; define it in a file "
            "or a notebook cell, or pass the code as a string."
        )
    try:
        block, start = inspect.getsourcelines(func)
    except (OSError, TypeError) as e:
        raise TraceError(f"can't find the source of {func.__qualname__}: {e}") from e
    window = lines or (start, start + len(block) - 1)

    shown = reprlib.Repr(maxlist=4, maxstring=24, maxother=24)
    parts = [shown.repr(a) for a in args]
    parts += [f"{k}={shown.repr(v)}" for k, v in (kwargs or {}).items()]
    req = TraceRequest(
        source=source,
        path=filename,
        function=func.__qualname__,
        args=", ".join(parts),
        stdin=stdin,
        limits=limits or Limits(),
        title=title,
        lines=window,
    )
    index = SourceIndex(source, filename)
    capture = Capture()
    tracer = Tracer(index, req.limits, capture)

    def body() -> None:
        tracer.install(code)
        fn(*args, **(kwargs or {}))

    error, _status = run_body(tracer, capture, stdin, filename, body)
    return finish_trace(req, tracer, error)
