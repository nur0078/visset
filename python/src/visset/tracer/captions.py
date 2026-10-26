"""Plain-English captions from templates (no AI needed).

A caption is written when a step is *finalized*, which happens when the next step begins.
At that moment we know both what the focused code did (by diffing the state before and after)
and where execution went next (so we can say "is true, so the loop body runs").

Inline code is wrapped in backticks; the player renders it as <code>.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .positions import StepNode

Value = dict[str, Any]


@dataclass(slots=True)
class CaptionContext:
    node: StepNode
    frame_name: str
    before: dict[str, Value] | None  # locals of this frame at the previous step (None: new)
    after: dict[str, Value]  # locals of this frame now
    changed_objects: set[str]  # object ids whose content changed during this step
    fmt: Callable[[Value], str]  # compact display of a value
    lookup: Callable[[str], Any] = lambda _oid: None  # object id -> current content
    next_node: StepNode | None = None
    next_same_frame: bool = False
    call: str | None = None  # "fib(n=3)" when this step called a function
    returned: Value | None = None  # return value when this step left the frame
    yielded: Value | None = None
    stdout: str = ""
    raised: str | None = None  # "ValueError: bad input"
    resumed_from: str | None = None  # "`fib(2)` returned `1`" when we came back from a call
    propagating: str | None = None  # exception type passing through this frame
    caught: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _code(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"`{text}`"


def _inside(lines: tuple[int, int] | None, node: StepNode | None) -> bool:
    return bool(lines and node and lines[0] <= node.focus_start[0] <= lines[1])


def _is_elif(node: StepNode, nxt: StepNode | None) -> bool:
    orelse = getattr(node.ast_node, "orelse", None)
    return bool(nxt is not None and orelse and len(orelse) == 1 and nxt.ast_node is orelse[0])


def _refs(value: Value) -> str | None:
    ref = value.get("ref")
    return ref if isinstance(ref, str) else None


def _target_caption(ctx: CaptionContext, target: tuple[str, ...]) -> str | None:
    """`self.val becomes 2` / `arr[3] becomes 9`, found by looking the value up."""
    obj = ctx.after.get(target[1])
    content = ctx.lookup(obj["ref"]) if obj and "ref" in obj else None
    if content is None:
        return None
    if target[0] == "attr":
        for name, val in content.get("fields", ()):
            if name == target[2]:
                return f"{_code(target[1] + '.' + name)} becomes {_code(ctx.fmt(val))}."
        return None
    if target[2] == "name":
        key_val = ctx.after.get(target[3])
        if not key_val or "p" not in key_val:
            return None
        key_text = key_val["p"]
    else:
        key_text = target[3]
    if content.get("shape") == "sequence":
        try:
            i = int(key_text)
        except ValueError:
            return None
        items = content.get("items", [])
        if -len(items) <= i < len(items):
            return f"{_code(f'{target[1]}[{key_text}]')} becomes {_code(ctx.fmt(items[i]))}."
    elif content.get("shape") == "mapping":
        for k, v in content.get("entries", ()):
            if k.get("p") == key_text:
                return f"{_code(f'{target[1]}[{key_text}]')} becomes {_code(ctx.fmt(v))}."
    return None


def changed_names(ctx: CaptionContext) -> list[str]:
    out: list[str] = []
    for name, val in ctx.after.items():
        old = ctx.before.get(name) if ctx.before is not None else None
        ref = _refs(val)
        if old != val or (ref is not None and ref in ctx.changed_objects):
            out.append(name)
    return out


def _changes(ctx: CaptionContext, names: list[str]) -> str:
    parts = []
    for name in names[:3]:
        val = ctx.after[name]
        old = ctx.before.get(name) if ctx.before else None
        ref = _refs(val)
        if old == val and ref is not None:
            parts.append(f"{_code(name)} is updated to {_code(ctx.fmt(val))}")
        else:
            parts.append(f"{_code(name)} becomes {_code(ctx.fmt(val))}")
    text = ", ".join(parts)
    if len(names) > 3:
        text += f", and {len(names) - 3} more change"
    return text[0].upper() + text[1:] + "."


def caption(ctx: CaptionContext) -> str:
    node, kind = ctx.node, ctx.node.kind
    test = _code(node.text)

    if ctx.raised:
        return f"{_code(ctx.raised, 80)} is raised here."
    if ctx.call:
        return f"Call {_code(ctx.call, 60)}."
    if ctx.yielded is not None:
        return f"{_code(ctx.frame_name)} yields {_code(ctx.fmt(ctx.yielded))} and pauses."
    if ctx.returned is not None and kind in ("Return", "Lambda"):
        return f"{_code(ctx.frame_name)} returns {_code(ctx.fmt(ctx.returned))}."

    if ctx.propagating:
        return f"The {_code(ctx.propagating)} reaches {_code(ctx.frame_name)}."

    branch = ctx.next_same_frame or ctx.next_node is None
    if kind == "If" and branch:
        if _inside(node.body_lines, ctx.next_node):
            return f"{test} is true, so the indented block runs."
        if _is_elif(node, ctx.next_node):
            return f"{test} is false, so the next condition is checked."
        if _inside(node.else_lines, ctx.next_node):
            return f"{test} is false, so the `else` branch runs."
        return f"{test} is false, so the block is skipped."
    if kind == "While" and branch:
        if node.text == "True" and _inside(node.body_lines, ctx.next_node):
            return "`while True` repeats until something inside the loop stops it."
        if _inside(node.body_lines, ctx.next_node):
            return f"{test} is true, so the loop body runs."
        return f"{test} is false, so the loop ends."
    if kind == "For" and branch:
        if _inside(node.body_lines, ctx.next_node):
            loop_vars = [n for n in node.names if n in ctx.after]
            if loop_vars:
                shown = ", ".join(
                    f"{_code(n)} = {_code(ctx.fmt(ctx.after[n]))}" for n in loop_vars[:2]
                )
                return f"Next item: {shown}."
            return "Take the next item."
        return "No items left, so the loop ends."

    names = changed_names(ctx)
    if ctx.resumed_from is not None:
        if names:
            return _changes(ctx, names)
        return f"Back in {_code(ctx.frame_name)}: {ctx.resumed_from}."

    if kind in ("If", "While", "For", "Match"):
        return f"Check {test}."
    if kind == "FunctionDef":
        return f"Define the function {_code(node.names[0])}."
    if kind == "ClassDef":
        return f"Define the class {_code(node.names[0])}."
    if kind == "ExceptHandler":
        return f"Catch the {_code(ctx.caught)}." if ctx.caught else f"Check {test}."
    if kind == "Return":
        return f"Return from {_code(ctx.frame_name)}."
    if kind == "Break":
        return "`break` leaves the loop."
    if kind == "Continue":
        return "`continue` jumps to the next loop iteration."
    if kind == "Pass":
        return "`pass` does nothing."
    if kind in ("Import", "ImportFrom"):
        return f"Import: {test}."
    if kind == "Raise":
        return f"Raise an exception: {test}."
    if kind == "Assert":
        return f"Check that {_code(node.text.removeprefix('assert').strip())} holds."
    if kind == "Delete":
        return f"Delete: {test}."

    if node.target and names:
        text = _target_caption(ctx, node.target)
        if text:
            return text
    if names and (kind != "Expr" or not ctx.stdout):
        return _changes(ctx, names)
    if ctx.stdout:
        return f"Print {_code(ctx.stdout.rstrip(chr(10)), 60)}."
    if kind in ("Assign", "AugAssign", "AnnAssign") and node.names:
        first = node.names[0]
        if first in ctx.after:
            return f"{_code(first)} stays {_code(ctx.fmt(ctx.after[first]))}."
    if kind == "GeneratorExp":
        return f"The generator expression {test} works on its next value."
    return f"Run {test}."
