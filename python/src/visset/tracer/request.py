"""The tracer protocol: what a tracer is asked to do (language-neutral JSON)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Limits:
    max_steps: int = 10_000
    timeout_ms: int = 5_000
    memory_mb: int = 512
    max_items: int = 50  # elements shown per container
    max_depth: int = 8  # nesting depth of objects shown
    max_stack: int = 100  # call depth before the trace stops (infinite recursion guard)

    def to_json(self) -> dict[str, int]:
        return {
            "maxSteps": self.max_steps,
            "timeoutMs": self.timeout_ms,
            "memoryMb": self.memory_mb,
            "maxItems": self.max_items,
            "maxDepth": self.max_depth,
            "maxStack": self.max_stack,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Limits:
        data = data or {}
        d = cls()
        return cls(
            max_steps=int(data.get("maxSteps", d.max_steps)),
            timeout_ms=int(data.get("timeoutMs", d.timeout_ms)),
            memory_mb=int(data.get("memoryMb", d.memory_mb)),
            max_items=int(data.get("maxItems", d.max_items)),
            max_depth=int(data.get("maxDepth", d.max_depth)),
            max_stack=int(data.get("maxStack", d.max_stack)),
        )


@dataclass(slots=True)
class TraceRequest:
    source: str
    path: str = "main.py"
    function: str | None = None  # None: run the module top level
    args: str = ""  # Python literal arguments, e.g. "[1, 3, 5], 3"
    stdin: str = ""
    limits: Limits = field(default_factory=Limits)
    output: str | None = None  # where a sandboxed child writes the trace
    title: str | None = None
    lines: tuple[int, int] | None = None  # view window: show only these lines (file numbering)
    given: str = ""  # snippet inputs as keyword literals: "arr=[1, 3, 5], target=3"

    def to_json(self) -> dict[str, Any]:
        return {
            "source": {"path": self.path, "text": self.source},
            "entry": {"function": self.function, "args": self.args} if self.function else None,
            "stdin": self.stdin,
            "limits": self.limits.to_json(),
            "output": self.output,
            "title": self.title,
            "view": {"lines": list(self.lines)} if self.lines else None,
            "given": self.given,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TraceRequest:
        entry = data.get("entry") or {}
        return cls(
            source=data["source"]["text"],
            path=data["source"].get("path") or "main.py",
            function=entry.get("function"),
            args=entry.get("args") or "",
            stdin=data.get("stdin") or "",
            limits=Limits.from_json(data.get("limits")),
            output=data.get("output"),
            title=data.get("title"),
            lines=_lines((data.get("view") or {}).get("lines")),
            given=data.get("given") or "",
        )


def _lines(value: Any) -> tuple[int, int] | None:
    if not value:
        return None
    first, last = value
    return int(first), int(last)
