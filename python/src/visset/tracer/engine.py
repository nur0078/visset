"""The Python tracer: run user code under `sys.monitoring` and record a visset trace.

How a step is born
------------------
1. `positions.SourceIndex` gives each user code object a table of *boundary* offsets: the
   instructions where a new step can begin.
2. We enable `INSTRUCTION` events only on user code objects. When a non-boundary instruction
   fires we return `DISABLE`, so it never fires again: after warm-up the tracer only runs at
   boundaries, and library code is never monitored at all.
3. At a boundary, the *pending* step (the code that just ran) is finalized with a snapshot of
   the state *after* it ran, and a new pending step starts for the code about to run.
4. `PY_RETURN` / `PY_YIELD` / `PY_UNWIND` finalize the step that leaves a frame, and create a
   "resumed" pending step in the caller (e.g. `x = f(1)` receiving its value).
"""

from __future__ import annotations

import _thread
import io
import sys
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .captions import CaptionContext, caption
from .positions import CodeTable, SourceIndex, StepNode, user_code_objects
from .request import Limits
from .snapshot import HeapEncoder, Value, compact

M = sys.monitoring
E = M.events
DISABLE = M.DISABLE
SOURCE_ID = "main"
_NO: Any = object()  # sentinel: "no value" (None is a real return value)


class StopTracing(BaseException):
    """Raised into user code when a limit is hit (in-process mode only).

    A BaseException, so a learner's `except Exception:` doesn't swallow it.
    """


class Capture(io.TextIOBase):
    """Collects what the program prints; each step takes the text printed during it."""

    def __init__(self, limit: int = 200_000) -> None:
        self._parts: list[str] = []
        self._size = 0
        self._limit = limit

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            raise TypeError(f"write() argument must be str, not {type(s).__name__}")
        if self._size < self._limit:
            room = self._limit - self._size
            self._parts.append(s if len(s) <= room else s[:room] + "\n… output truncated\n")
            self._size += len(s)
        return len(s)

    def take(self) -> str:
        text = "".join(self._parts)
        self._parts.clear()
        return text


@dataclass(slots=True, eq=False)
class FrameState:
    frame: types.FrameType
    fid: str
    node: StepNode | None = None
    offset: int = -1


@dataclass(slots=True)
class Pending:
    frame: types.FrameType
    node: StepNode
    resumed_from: str | None = None
    propagating: str | None = None


class Tracer:
    def __init__(self, index: SourceIndex, limits: Limits, capture: Capture) -> None:
        self.index = index
        self.limits = limits
        self.capture = capture
        self.heap = HeapEncoder(limits.max_items, limits.max_depth)
        self.steps: list[dict[str, Any]] = []
        self.truncated: dict[str, Any] | None = None
        self.on_limit: Callable[[], None] = self._raise_stop
        self._tables: dict[int, CodeTable] = {}
        self._frames: dict[int, FrameState] = {}
        self._pending: Pending | None = None
        self._prev_locals: dict[str, dict[str, Value]] = {}
        self._prev_versions: dict[str, str] = {}
        self._busy = False
        self._fid_count = 0
        self._tool: int | None = None
        self._codes: list[types.CodeType] = []
        self._deadline = float("inf")
        self._thread = _thread.get_ident()
        self._reported_exc: BaseException | None = None
        self._caught: str | None = None

    # ------------------------------------------------------------------ lifecycle

    def install(self, module_code: types.CodeType) -> None:
        for tool in (4, 3, 0, 1, 2):
            try:
                M.use_tool_id(tool, "visset")
            except ValueError:
                continue
            self._tool = tool
            break
        else:
            raise RuntimeError("no free sys.monitoring tool id (is another debugger running?)")
        tool = self._tool
        M.register_callback(tool, E.INSTRUCTION, self._on_instruction)
        M.register_callback(tool, E.PY_RETURN, self._on_return)
        M.register_callback(tool, E.PY_YIELD, self._on_yield)
        M.register_callback(tool, E.PY_UNWIND, self._on_unwind)
        M.register_callback(tool, E.EXCEPTION_HANDLED, self._on_handled)
        local = E.INSTRUCTION | E.PY_RETURN | E.PY_YIELD
        for code in user_code_objects(module_code):
            self._tables[id(code)] = self.index.table(code)
            self._codes.append(code)
            M.set_local_events(tool, code, local)
        # Unwinding and handling are "non-local" events: they can only be enabled globally.
        M.set_events(tool, E.PY_UNWIND | E.EXCEPTION_HANDLED)
        self._deadline = time.perf_counter() + self.limits.timeout_ms / 1000

    def uninstall(self) -> None:
        tool = self._tool
        if tool is None:
            return
        self._tool = None
        M.set_events(tool, 0)
        for code in self._codes:
            M.set_local_events(tool, code, 0)
        for event in (E.INSTRUCTION, E.PY_RETURN, E.PY_YIELD, E.PY_UNWIND, E.EXCEPTION_HANDLED):
            M.register_callback(tool, event, None)
        M.free_tool_id(tool)

    # ------------------------------------------------------------------ callbacks (hot path)

    def _on_instruction(self, code: types.CodeType, offset: int) -> Any:
        if self._busy:
            return None
        table = self._tables.get(id(code))
        if table is None or offset not in table.boundaries:
            return DISABLE
        if _thread.get_ident() != self._thread:
            return None  # only the main thread is visualized
        frame = sys._getframe(1)
        node = table.node_at[offset]
        state = self._frames.get(id(frame))
        if (
            state is not None
            and state.node is node
            and (offset > state.offset or offset not in table.starts)
        ):
            # Same node, moving forward, or looping *inside* it (a comprehension):
            # not a new step. Re-entering at the node's start (a one-line loop body) is.
            state.offset = offset
            return None
        self._busy = True
        try:
            self._boundary(frame, state, node, offset)
        finally:
            self._busy = False
        return None

    def _on_return(self, code: types.CodeType, offset: int, value: object) -> Any:
        if self._busy or id(code) not in self._tables or _thread.get_ident() != self._thread:
            return None
        self._busy = True
        try:
            frame = sys._getframe(1)
            if code.co_name == "<module>":
                self._finalize(frame)  # the program ends; a module has no return value
            else:
                self._finalize(frame, returned=value)
            shown = self._last_return_display()
            self._frames.pop(id(frame), None)
            self._resume_caller(frame, f"{_q(code.co_qualname)} returned {_q(shown)}")
        finally:
            self._busy = False
        return None

    def _on_yield(self, code: types.CodeType, offset: int, value: object) -> Any:
        if self._busy or id(code) not in self._tables or _thread.get_ident() != self._thread:
            return None
        self._busy = True
        try:
            frame = sys._getframe(1)
            self._finalize(frame, yielded=value)
            shown = self._last_return_display()
            self._resume_caller(frame, f"{_q(code.co_qualname)} produced {_q(shown)}")
        finally:
            self._busy = False
        return None

    def _on_unwind(self, code: types.CodeType, offset: int, exc: BaseException) -> Any:
        if self._busy or id(code) not in self._tables or _thread.get_ident() != self._thread:
            return None
        if isinstance(exc, StopTracing):
            return None
        self._busy = True
        try:
            frame = sys._getframe(1)
            raised = None
            if exc is not self._reported_exc:
                self._reported_exc = exc
                raised = _exc_text(exc)
            self._finalize(frame, raised=raised)
            self._frames.pop(id(frame), None)
            self._resume_caller(frame, None, propagating=type(exc).__name__)
        finally:
            self._busy = False
        return None

    def _on_handled(self, code: types.CodeType, offset: int, exc: BaseException) -> Any:
        if id(code) in self._tables and not self._busy:
            self._caught = type(exc).__name__
            if self._pending is not None and exc is not self._reported_exc:
                # Raised and caught inside the same frame: the pending step is where it happened.
                self._reported_exc = exc
                self._pending_raised = _exc_text(exc)
        return None

    # ------------------------------------------------------------------ step bookkeeping

    _pending_raised: str | None = None

    def _boundary(
        self, frame: types.FrameType, state: FrameState | None, node: StepNode, offset: int
    ) -> None:
        is_call = state is None
        if state is None:
            state = self._register(frame)
            if len(self._frames) > self.limits.max_stack:
                self._stop("maxStack", self.limits.max_stack, frame)
        state.node, state.offset = node, offset
        self._finalize(frame, next_node=node, next_frame=frame, is_call=is_call)
        self._pending = Pending(frame, node)
        if time.perf_counter() > self._deadline:
            self._stop("timeout", self.limits.timeout_ms, frame)

    def _register(self, frame: types.FrameType) -> FrameState:
        self._fid_count += 1
        state = FrameState(frame, f"f{self._fid_count}")
        self._frames[id(frame)] = state
        return state

    def _resume_caller(
        self,
        frame: types.FrameType,
        resumed_from: str | None,
        propagating: str | None = None,
    ) -> None:
        caller = frame.f_back
        while caller is not None and id(caller.f_code) not in self._tables:
            caller = caller.f_back
        self._pending = None
        if caller is None:
            return
        state = self._frames.get(id(caller))
        node = self._tables[id(caller.f_code)].node_at.get(caller.f_lasti)
        if node is None and state is not None:
            node = state.node
        if node is not None:
            self._pending = Pending(caller, node, resumed_from, propagating)

    def _stop(self, reason: str, limit: int, frame: types.FrameType) -> None:
        if self.truncated is not None:
            return
        self.truncated = {"reason": reason, "limit": limit}
        self._finalize(frame)
        self.uninstall()
        self.on_limit()

    @staticmethod
    def _raise_stop() -> None:
        raise StopTracing

    def stop_from_signal(self, frame: types.FrameType | None) -> None:
        """Wall-clock timeout fired while the program was stuck outside our callbacks."""
        if self.truncated is None:
            self.truncated = {"reason": "timeout", "limit": self.limits.timeout_ms}
        if not self._busy and frame is not None:
            while frame is not None and id(frame.f_code) not in self._tables:
                frame = frame.f_back
            if frame is not None:
                self._busy = True
                self._finalize(frame)

    def finish(self) -> None:
        """Called after the program ends: finalize anything still pending."""
        if self._pending is not None:
            self._finalize(self._pending.frame)

    # ------------------------------------------------------------------ snapshots

    def _user_frames(self, top: types.FrameType) -> list[types.FrameType]:
        frames = []
        f: types.FrameType | None = top
        while f is not None:
            if id(f.f_code) in self._tables:
                frames.append(f)
            f = f.f_back
        frames.reverse()
        return frames

    def _locals(self, frame: types.FrameType) -> list[tuple[str, object]]:
        code = frame.f_code
        if code.co_name == "<module>":
            return [
                (k, v)
                for k, v in frame.f_globals.items()
                if not k.startswith("__") and not isinstance(v, types.ModuleType)
            ]
        f_locals = frame.f_locals
        out = []
        seen = set()
        for name in (*code.co_varnames, *code.co_cellvars, *code.co_freevars):
            if name in seen or name.startswith("."):
                continue
            seen.add(name)
            try:
                if name in f_locals:
                    out.append((name, f_locals[name]))
            except (KeyError, ValueError):  # empty cell
                continue
        return out

    def _snapshot(
        self, top: types.FrameType, attach: tuple[str, object] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Value]], list[str]]:
        heap = self.heap
        heap.begin()
        stack: list[dict[str, Any]] = []
        by_fid: dict[str, dict[str, Value]] = {}
        frames = self._user_frames(top)
        for f in frames:
            state = self._frames.get(id(f)) or self._register(f)
            pairs = [(name, heap.value(v)) for name, v in self._locals(f)]
            by_fid[state.fid] = dict(pairs)
            entry: dict[str, Any] = {
                "id": state.fid,
                "name": "Global" if f.f_code.co_name == "<module>" else f.f_code.co_qualname,
                "line": f.f_lineno or 0,
                "locals": [[n, v] for n, v in pairs],
            }
            stack.append(entry)
        if attach is not None and stack:
            stack[-1][attach[0]] = heap.value(attach[1])
        live = heap.end()
        return stack, by_fid, live

    def _last_return_display(self) -> str:
        if not self.steps:
            return "?"
        top = self.steps[-1]["stack"][-1] if self.steps[-1]["stack"] else {}
        value = top.get("returnValue") or top.get("yieldValue")
        return self._fmt(value) if value else "?"

    def _fmt(self, value: Value) -> str:
        return compact(value, self.heap.latest)

    def _finalize(
        self,
        top: types.FrameType,
        *,
        next_node: StepNode | None = None,
        next_frame: types.FrameType | None = None,
        is_call: bool = False,
        returned: object = _NO,
        yielded: object = _NO,
        raised: str | None = None,
    ) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        if raised is None and self._pending_raised is not None:
            raised = self._pending_raised
        self._pending_raised = None

        attach = None
        if returned is not _NO:
            attach = ("returnValue", returned)
        elif yielded is not _NO:
            attach = ("yieldValue", yielded)
        stack, by_fid, live = self._snapshot(top, attach)

        versions: dict[str, str] = {}
        for vid in live:
            oid, _, ver = vid.partition("@")
            versions[oid] = ver
        changed = {o for o, v in versions.items() if self._prev_versions.get(o, v) != v}
        if changed:
            changed = self._with_ancestors(changed, live)

        state = self._frames.get(id(pending.frame))
        fid = state.fid if state else ""
        frame_name = (
            "Global"
            if pending.frame.f_code.co_name == "<module>"
            else pending.frame.f_code.co_qualname
        )
        call = None
        if is_call and next_frame is not None and next_frame is not pending.frame:
            call = self._call_text(next_frame, by_fid)

        top_entry = stack[-1] if stack else {}
        ctx = CaptionContext(
            node=pending.node,
            frame_name=frame_name,
            before=self._prev_locals.get(fid, {}),
            after=by_fid.get(fid, {}),
            changed_objects=changed,
            fmt=self._fmt,
            lookup=self.heap.latest,
            next_node=next_node,
            next_same_frame=next_frame is pending.frame,
            call=call,
            returned=top_entry.get("returnValue"),
            yielded=top_entry.get("yieldValue"),
            stdout="",
            raised=raised,
            resumed_from=pending.resumed_from,
            propagating=pending.propagating,
            caught=self._caught if pending.node.kind == "ExceptHandler" else None,
        )
        out = self.capture.take()
        ctx.stdout = out
        if raised:
            kind = "exception"
        elif call:
            kind = "call"
        elif attach is not None:
            kind = "return"
        else:
            kind = "statement"
        node = pending.node
        mark: dict[str, Any] = {
            "source": SOURCE_ID,
            "start": list(node.focus_start),
            "end": list(node.focus_end),
            "mark": node.mark,
        }
        if raised:
            mark["tone"] = "error"
        step: dict[str, Any] = {
            "kind": kind,
            "focus": [mark],
            "caption": caption(ctx),
            "captionOrigin": "template",
            "stack": stack,
            "heap": live,
        }
        if out:
            step["stdout"] = out
        self.steps.append(step)
        self._prev_locals = by_fid
        self._prev_versions = versions
        if len(self.steps) >= self.limits.max_steps and self.truncated is None:
            self.truncated = {"reason": "maxSteps", "limit": self.limits.max_steps}
            self.uninstall()
            self.on_limit()

    def _with_ancestors(self, changed: set[str], live: list[str]) -> set[str]:
        """An object counts as changed if anything it (transitively) refers to changed."""
        parents: dict[str, set[str]] = {}
        for vid in live:
            parent = vid.partition("@")[0]
            for child in _child_refs(self.heap.objects[vid]):
                parents.setdefault(child, set()).add(parent)
        out = set(changed)
        todo = list(changed)
        while todo:
            for parent in parents.get(todo.pop(), ()):
                if parent not in out:
                    out.add(parent)
                    todo.append(parent)
        return out

    def _call_text(self, frame: types.FrameType, by_fid: dict[str, dict[str, Value]]) -> str:
        code = frame.f_code
        state = self._frames.get(id(frame))
        local = by_fid.get(state.fid, {}) if state else {}
        n = code.co_argcount + code.co_kwonlyargcount
        n += bool(code.co_flags & 0x04) + bool(code.co_flags & 0x08)
        args = [
            f"{p}={compact(local[p], self.heap.latest, 20)}"
            for p in code.co_varnames[:n]
            if p in local
        ]
        return f"{code.co_qualname}({', '.join(args)})"


def _child_refs(content: dict[str, Any]) -> list[str]:
    vals: list[Value] = []
    vals.extend(content.get("items", ()))
    for k, v in content.get("entries", ()):
        vals += (k, v)
    vals.extend(v for _, v in content.get("fields", ()))
    return [v["ref"] for v in vals if "ref" in v]


def _q(text: str) -> str:
    return f"`{text}`"


def _exc_text(exc: BaseException) -> str:
    msg = str(exc)
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__
