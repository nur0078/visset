"""View windows: show only part of the source (one function, or a range of lines).

The program still runs as a whole; the window decides which steps a learner sees and which
lines the code pane shows. Steps are recorded normally, then filtered and renumbered here, so
every kept step still shows the full state *after* its code ran.
"""

from __future__ import annotations

import ast
from typing import Any


class WindowError(ValueError):
    pass


def parse_lines(text: str) -> tuple[int, int]:
    """'4-9' or '7' -> (4, 9) / (7, 7)."""
    try:
        a, _, b = text.partition("-")
        first, last = int(a), int(b or a)
    except ValueError as e:
        raise WindowError(f"--lines must look like 4-9 or 7, not {text!r}") from e
    if first < 1 or last < first:
        raise WindowError(f"--lines {text}: expected 1 <= first <= last")
    return first, last


def function_range(source: str, qualname: str) -> tuple[int, int]:
    """Lines of the definition of `name` or `Class.method` (decorators included)."""
    Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    body: list[ast.stmt] = ast.parse(source).body
    node: Def | None = None
    for part in qualname.split("."):
        node = next((n for n in body if isinstance(n, Def) and n.name == part), None)
        if node is None:
            raise WindowError(f"no function or class named {qualname!r} at the top level")
        body = node.body
    assert node is not None
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return first, node.end_lineno or node.lineno


def apply_window(trace: dict[str, Any], first: int, last: int) -> dict[str, Any]:
    """Keep steps focused inside lines first..last and renumber everything to the excerpt."""
    source = trace["sources"][0]
    lines = source["text"].splitlines(keepends=True)
    last = min(last, len(lines))
    if first > last:
        raise WindowError(f"line {first} is past the end of the file ({len(lines)} lines)")
    shift = first - 1
    source["text"] = "".join(lines[first - 1 : last])
    source["firstLine"] = first
    source["tokens"] = [
        [ln - shift, c, e, k] for ln, c, e, k in source.get("tokens", []) if first <= ln <= last
    ]

    kept: list[dict[str, Any]] = []
    carry = ""  # output printed by hidden steps rides along with the next visible one
    for step in trace["steps"]:
        marks = step["focus"]
        inside = bool(marks) and all(first <= m["start"][0] and m["end"][0] <= last for m in marks)
        if not inside:
            carry += step.get("stdout", "")
            continue
        if carry:
            step["stdout"] = carry + step.get("stdout", "")
            carry = ""
        for m in marks:
            m["start"] = [m["start"][0] - shift, m["start"][1]]
            m["end"] = [m["end"][0] - shift, m["end"][1]]
        for frame in step["stack"]:
            line = frame.get("line")
            if line is not None and first <= line <= last:
                frame["line"] = line - shift
            else:
                frame.pop("line", None)
        kept.append(step)
    if carry and kept:
        kept[-1]["stdout"] = kept[-1].get("stdout", "") + carry
    trace["steps"] = kept

    live = {vid for step in kept for vid in step["heap"]}
    trace["objects"] = {vid: obj for vid, obj in trace["objects"].items() if vid in live}
    return trace
