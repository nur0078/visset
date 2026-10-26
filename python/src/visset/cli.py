"""`visset` command line. Imports are lazy so `visset --help` starts instantly."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _add_trace_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("file", help="Python file to trace")
    p.add_argument(
        "--fn",
        metavar="NAME",
        help="trace one call of this function (or Class.method); shows only its source",
    )
    p.add_argument(
        "--lines",
        metavar="A-B",
        help="show only these lines, e.g. 4-9 (part of a function); the program still runs",
    )
    p.add_argument(
        "--given",
        default="",
        metavar="INPUTS",
        help='inputs for a snippet, e.g. "arr=[1, 3, 5], target=3"',
    )
    p.add_argument(
        "--args",
        default="",
        metavar="ARGS",
        help='arguments for --fn as Python literals, e.g. "[1, 3, 5], 3"',
    )
    p.add_argument(
        "--stdin", default=None, metavar="TEXT", help="text the program reads via input()"
    )
    p.add_argument("--max-steps", type=int, default=10_000, metavar="N")
    p.add_argument("--timeout", type=float, default=5.0, metavar="SECONDS")
    p.add_argument(
        "--no-sandbox",
        action="store_true",
        help="run in this process: faster start, no time/memory protection",
    )


def _parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="visset",
        description="Step-by-step visual explanations of code.",
    )
    parser.add_argument("--version", action="version", version=f"visset {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = sub.add_parser("run", help="trace a file and open the walkthrough (or export with -o)")
    _add_trace_args(run)
    run.add_argument(
        "-o", "--output", metavar="FILE.html", help="write HTML here instead of opening"
    )
    run.add_argument("--open", action="store_true", help="open in the browser even with -o")

    trace = sub.add_parser("trace", help="trace a file and write the raw JSON trace")
    _add_trace_args(trace)
    trace.add_argument("-o", "--output", metavar="FILE.json", help="default: stdout")

    render = sub.add_parser("render", help="render a JSON trace to HTML")
    render.add_argument("trace", help="trace .json file")
    render.add_argument("-o", "--output", metavar="FILE.html")
    render.add_argument("--open", action="store_true")
    return parser


def _trace(ns: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .tracer import Limits, TraceRequest, execute, run_sandboxed

    path = Path(ns.file)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"visset: cannot read {path}: {e.strerror}") from e
    from .tracer.window import WindowError, parse_lines

    try:
        lines = parse_lines(ns.lines) if ns.lines else None
    except WindowError as e:
        raise SystemExit(f"visset: {e}") from e
    req = TraceRequest(
        source=source,
        path=str(path.resolve()),
        function=ns.fn,
        args=ns.args,
        given=ns.given,
        lines=lines,
        stdin=ns.stdin or "",
        limits=Limits(max_steps=ns.max_steps, timeout_ms=int(ns.timeout * 1000)),
    )
    return execute(req) if ns.no_sandbox else run_sandboxed(req)


def _report(trace: dict[str, Any]) -> None:
    meta = trace["meta"]
    n = len(trace["steps"])
    err = sys.stderr
    first = trace["sources"][0].get("firstLine")
    if n == 0 and first:
        err.write("note: no code ran inside the selected lines.\n")
    if meta.get("error"):
        e = meta["error"]
        where = f" on line {e['line']}" if e.get("line") else ""
        err.write(f"note: the program raised {e['type']}{where}; the walkthrough ends there.\n")
    if meta.get("truncated"):
        t = meta["truncated"]
        why = {
            "maxSteps": f"after {t['limit']:,} steps",
            "timeout": f"after {t['limit'] / 1000:g}s",
            "maxStack": f"at {t['limit']} nested calls",
        }.get(t["reason"], t["reason"])
        err.write(f"note: tracing stopped {why}; the walkthrough shows what ran until then.\n")
    err.write(f"{n} step{'s' if n != 1 else ''} recorded.\n")


def main(argv: list[str] | None = None) -> int:
    ns = _parser().parse_args(argv)
    from .tracer import TraceError

    try:
        if ns.command == "render":
            trace = json.loads(Path(ns.trace).read_text(encoding="utf-8"))
            return _emit_html(trace, ns.output, ns.open)
        trace, _status = _trace(ns)
    except TraceError as e:
        sys.stderr.write(f"visset: {e}\n")
        return 1
    _report(trace)
    if ns.command == "trace":
        text = json.dumps(trace, ensure_ascii=False, indent=None, separators=(",", ":"))
        if ns.output:
            Path(ns.output).write_text(text, encoding="utf-8")
        else:
            sys.stdout.write(text + "\n")
        return 0
    return _emit_html(trace, ns.output, ns.open)


def _emit_html(trace: dict[str, Any], output: str | None, force_open: bool) -> int:
    from .export.html import PlayerMissingError, open_in_browser, render_html

    try:
        if output and not force_open:
            Path(output).write_text(render_html(trace), encoding="utf-8")
            sys.stderr.write(f"wrote {output}\n")
        else:
            path = open_in_browser(trace, output)
            sys.stderr.write(f"opened {path}\n")
    except PlayerMissingError as e:
        sys.stderr.write(f"visset: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
