"""Run a TraceRequest: in this process, or in a sandboxed child process (the default).

The child is started as `python -I -c <bootstrap>` and receives the request as JSON on stdin.
It writes the trace to a file, not to stdout, because stdout belongs to the user's program.
"""

from __future__ import annotations

import ast
import builtins
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .._version import __version__
from .engine import Capture, StopTracing, Tracer
from .positions import SourceIndex
from .request import TraceRequest
from .tokens import python_tokens

SCHEMA = "visset.trace/0.1"

EXIT_OK, EXIT_FAILED, EXIT_USER_ERROR, EXIT_LIMIT = 0, 1, 2, 3


class TraceError(RuntimeError):
    """The tracer itself failed (not the user's program)."""


# ---------------------------------------------------------------------------- trace assembly


def _meta(req: TraceRequest) -> dict[str, Any]:
    entry = f"{req.function}({req.args})" if req.function else None
    return {
        "language": "python",
        "runtime": f"{platform.python_implementation()} {platform.python_version()}",
        "generator": f"visset {__version__}",
        "origin": "traced",
        "title": req.title or entry or Path(req.path).name,
        "entry": entry,
        "truncated": None,
        "error": None,
    }


def _result(
    req: TraceRequest,
    tracer: Tracer | None,
    error: dict[str, Any] | None,
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = _meta(req)
    meta["error"] = error
    if tracer is not None:
        meta["truncated"] = tracer.truncated
    return {
        "schema": SCHEMA,
        "meta": meta,
        "sources": [
            {
                "id": "main",
                "path": Path(req.path).name,
                "text": req.source,
                "tokens": python_tokens(req.source),
            }
        ],
        "objects": tracer.heap.objects if tracer else {},
        "steps": tracer.steps if tracer else (steps or []),
    }


def _syntax_error_trace(req: TraceRequest, exc: SyntaxError) -> dict[str, Any]:
    lines = req.source.splitlines() or [""]
    line = max(1, min(exc.lineno or 1, len(lines)))
    text = lines[line - 1]
    col = max(0, min((exc.offset or 1) - 1, len(text)))
    end_line = exc.end_lineno or line
    end_col = (exc.end_offset or 0) - 1
    if end_line != line or end_col <= col:
        end_line, end_col = line, max(col + 1, len(text.rstrip()))
    message = f"SyntaxError: {exc.msg}"
    step = {
        "kind": "exception",
        "focus": [
            {
                "source": "main",
                "start": [line, col],
                "end": [end_line, end_col],
                "mark": "underline",
                "tone": "error",
            }
        ],
        "caption": f"`{message}`. Python can't run the program until this is fixed.",
        "captionOrigin": "template",
        "stack": [],
        "heap": [],
    }
    error = {"type": "SyntaxError", "message": exc.msg, "line": line}
    return _result(req, None, error, [step])


def _parse_args(args: str) -> tuple[Any, ...]:
    if not args.strip():
        return ()
    try:
        value = ast.literal_eval(f"({args},)")
    except (ValueError, SyntaxError) as e:
        raise TraceError(f'--args must be Python literals, e.g. "[1, 2, 3], 2" ({e})') from e
    return tuple(value)


# ---------------------------------------------------------------------------- execution


def execute(req: TraceRequest, on_limit: Any = None) -> tuple[dict[str, Any], int]:
    """Trace `req` in *this* process. Returns (trace, exit code)."""
    try:
        index = SourceIndex(req.source, req.path)
        code = compile(req.source, req.path, "exec")
    except SyntaxError as exc:
        return _syntax_error_trace(req, exc), EXIT_USER_ERROR

    capture = Capture()
    tracer = Tracer(index, req.limits, capture)
    global _ACTIVE
    _ACTIVE = (req, tracer)
    if on_limit is not None:
        tracer.on_limit = lambda: on_limit(_result(req, tracer, None))
    ns: dict[str, Any] = {"__name__": "__main__", "__file__": req.path, "__builtins__": builtins}
    saved = sys.stdout, sys.stdin
    sys.stdout, sys.stdin = capture, _EchoStdin(req.stdin, capture)
    error: dict[str, Any] | None = None
    status = EXIT_OK
    try:
        if req.function:
            exec(code, ns)  # define things, untraced
            capture.take()
            fn = ns.get(req.function)
            if not callable(fn):
                raise TraceError(f"{req.function!r} is not a function defined in {req.path}")
            args = _parse_args(req.args)
            tracer.install(code)
            fn(*args)
        else:
            tracer.install(code)
            exec(code, ns)
    except StopTracing:
        status = EXIT_LIMIT
    except TraceError:
        raise
    except SystemExit as exc:
        if exc.code not in (None, 0):
            error = {"type": "SystemExit", "message": str(exc.code), "line": None}
            status = EXIT_USER_ERROR
    except BaseException as exc:  # the user's program raised: still a valid trace
        tb = exc.__traceback__
        line = None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == req.path:
                line = tb.tb_lineno
            tb = tb.tb_next
        error = {"type": type(exc).__name__, "message": str(exc), "line": line}
        status = EXIT_USER_ERROR
    finally:
        tracer.uninstall()
        sys.stdout, sys.stdin = saved
    tracer.finish()
    if tracer.truncated is not None and status == EXIT_OK:
        status = EXIT_LIMIT
    return _result(req, tracer, error), status


_ACTIVE: tuple[TraceRequest, Tracer] | None = None


class _EchoStdin(io.StringIO):
    """Feeds the request's stdin to input(), echoing it like a terminal would."""

    def __init__(self, text: str, echo: Capture) -> None:
        super().__init__(text)
        self._echo = echo

    def readline(self, size: int | None = -1) -> str:  # type: ignore[override]
        line = super().readline(-1 if size is None else size)
        self._echo.write(line if line.endswith("\n") or not line else line + "\n")
        return line


def _dumps(obj: Any) -> bytes:
    try:
        import orjson  # optional: ~5x faster

        return bytes(orjson.dumps(obj))
    except ImportError:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def child_main() -> None:
    """Entry point inside the sandboxed child process."""
    req = TraceRequest.from_json(json.loads(sys.stdin.buffer.read()))
    out_path = req.output
    if not out_path:
        raise SystemExit("visset child: missing output path")
    _apply_rlimits(req)

    def write(trace: dict[str, Any]) -> None:
        with open(out_path, "wb") as f:
            f.write(_dumps(trace))

    def on_limit(trace: dict[str, Any]) -> None:
        # Exceptions raised from a monitoring callback surface in user code, where a bare
        # `except:` could swallow them. So: write what we have and leave immediately.
        write(trace)
        os._exit(EXIT_LIMIT)

    sys.setrecursionlimit(max(sys.getrecursionlimit(), req.limits.max_stack + 200))
    _arm_alarm(req, write)
    try:
        trace, status = execute(req, on_limit=on_limit)
    except TraceError as e:
        sys.stderr.write(f"{e}\n")
        os._exit(EXIT_FAILED)
    write(trace)
    sys.stdout.flush()
    os._exit(status)


def _arm_alarm(req: TraceRequest, write: Any) -> None:
    """Backstop for programs stuck where no step fires (e.g. `time.sleep(60)`).

    The step-level deadline check can't run while the program sits inside a C call, but a
    signal handler runs as soon as the interpreter regains control.
    """
    import signal

    if not hasattr(signal, "setitimer"):
        return

    def on_alarm(signum: int, frame: Any) -> None:
        if _ACTIVE is not None:
            areq, tracer = _ACTIVE
            tracer.stop_from_signal(frame)
            write(_result(areq, tracer, None))
        os._exit(EXIT_LIMIT)

    signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, req.limits.timeout_ms / 1000 + 0.25)


def _apply_rlimits(req: TraceRequest) -> None:
    try:
        import resource
    except ImportError:  # Windows: wall-clock timeout and step limit only
        return
    cpu = max(1, -(-req.limits.timeout_ms // 1000) + 1)
    for limit, value in (
        (resource.RLIMIT_CPU, cpu),
        (resource.RLIMIT_AS, req.limits.memory_mb * 1024 * 1024),
    ):
        try:
            _soft, hard = resource.getrlimit(limit)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(limit, (value, hard))
        except (ValueError, OSError):  # e.g. RLIMIT_AS unsupported on macOS
            continue


_BOOTSTRAP = (
    "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(1, sys.argv[2]); "
    "from visset.tracer.run import child_main; child_main()"
)


def run_sandboxed(req: TraceRequest, python: str | None = None) -> tuple[dict[str, Any], int]:
    """Trace `req` in a child process with time and memory limits."""
    package_root = str(Path(__file__).resolve().parents[2])  # the dir containing `visset/`
    user_dir = str(Path(req.path).resolve().parent) if req.path else os.getcwd()
    with tempfile.TemporaryDirectory(prefix="visset-") as tmp:
        out = os.path.join(tmp, "trace.json")
        payload = TraceRequest.from_json(req.to_json())
        payload.output = out
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "0",  # deterministic set/dict-of-str order: reproducible traces
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        }
        cwd = user_dir if os.path.isdir(user_dir) else tmp
        timeout = req.limits.timeout_ms / 1000 + 2
        try:
            proc = subprocess.run(
                [python or sys.executable, "-I", "-c", _BOOTSTRAP, package_root, user_dir],
                input=json.dumps(payload.to_json()).encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise TraceError(
                f"the program ran longer than {timeout:.0f}s without reaching a step "
                "(stuck inside a library call or sleep?)"
            ) from e
        if not os.path.exists(out):
            detail = proc.stderr.decode("utf-8", "replace").strip()
            if proc.returncode < 0 or proc.returncode in (137, 152):
                detail = detail or "killed by the CPU or memory limit"
            raise TraceError(f"tracer failed (exit {proc.returncode}): {detail[-2000:]}")
        with open(out, "rb") as f:
            trace = json.loads(f.read())
        return trace, proc.returncode
