"""Encode Python values into the trace's language-neutral value and object format.

Values are either primitives `{"p": display, "t": type}` or references `{"ref": "o3"}`.
Referenced objects live in a *versioned pool*: `o3@0`, `o3@1`, ... A new version is stored only
when an object's encoded content changes, so an array that sits untouched for 500 steps is
stored once, yet every step still lists exactly which versions are alive (O(1) seeking).

This module decides what the learner sees, so it maps Python's types onto a handful of
neutral *shapes*: sequence, mapping, set, record, function, class, opaque.
"""

from __future__ import annotations

import enum
import types
from collections import deque
from typing import Any

Value = dict[str, Any]
Content = dict[str, Any]

_PRIM_TYPES: dict[type, str] = {
    int: "int",
    float: "float",
    bool: "bool",
    complex: "complex",
    str: "str",
    bytes: "bytes",
    type(None): "None",
}

MAX_STR = 120


def prim(obj: object) -> Value:
    t = type(obj)
    if t is str:
        s: str = obj  # type: ignore[assignment]
        text = repr(s) if len(s) <= MAX_STR else repr(s[:MAX_STR]) + "…"
        return {"p": text, "t": "str"}
    if t is int:
        try:
            text = repr(obj)
        except ValueError:  # beyond sys.get_int_max_str_digits()
            text = f"<int with {obj.bit_length() * 30103 // 100000 + 1} digits>"  # type: ignore[attr-defined]
        return {"p": text, "t": "int"}
    text = repr(obj)
    if len(text) > MAX_STR:
        text = text[:MAX_STR] + "…"
    return {"p": text, "t": _PRIM_TYPES.get(t, t.__name__)}


def _type_name(obj: object) -> str:
    return type(obj).__qualname__


def _signature(fn: types.FunctionType) -> str:
    code = fn.__code__
    n = code.co_argcount + code.co_kwonlyargcount
    params = list(code.co_varnames[:n])
    if code.co_flags & 0x04:  # *args
        params.insert(code.co_argcount, "*" + code.co_varnames[n])
        n += 1
    if code.co_flags & 0x08:  # **kwargs
        params.append("**" + code.co_varnames[n])
    return f"{fn.__qualname__}({', '.join(params)})"


class HeapEncoder:
    """Assigns stable ids to objects and records a new version whenever content changes."""

    def __init__(self, max_items: int = 50, max_depth: int = 8, max_objects: int = 300) -> None:
        self.max_items = max_items
        self.max_depth = max_depth
        self.max_objects = max_objects
        self.objects: dict[str, Content] = {}  # "o3@1" -> content, written to the trace
        self._ids: dict[int, str] = {}
        self._keep: list[object] = []  # strong refs so id() is never reused mid-trace
        self._latest: dict[str, tuple[int, Content]] = {}
        self._queue: deque[tuple[object, str, int]] = deque()
        self._seen: dict[str, object] = {}

    # --------------------------------------------------------------------------- public

    def begin(self) -> None:
        self._queue.clear()
        self._seen = {}

    def value(self, obj: object, depth: int = 0) -> Value:
        """Encode a value; references are queued for `end()` to snapshot."""
        if type(obj) in _PRIM_TYPES:
            return prim(obj)
        if isinstance(obj, enum.Enum):
            return {"p": f"{type(obj).__name__}.{obj.name}", "t": _type_name(obj)}
        if depth > self.max_depth or (
            len(self._seen) >= self.max_objects and id(obj) not in self._ids
        ):
            return {"p": "…", "t": _type_name(obj)}
        oid = self._oid(obj)
        if oid not in self._seen:
            if len(self._seen) >= self.max_objects:
                return {"p": "…", "t": _type_name(obj)}
            self._seen[oid] = obj
            self._queue.append((obj, oid, depth))
        return {"ref": oid}

    def end(self) -> list[str]:
        """Snapshot every queued object (breadth-first); return the live version ids."""
        live: list[str] = []
        while self._queue:
            obj, oid, depth = self._queue.popleft()
            content = self._content(obj, depth)
            prev = self._latest.get(oid)
            if prev is not None and prev[1] == content:
                version = prev[0]
            else:
                version = 0 if prev is None else prev[0] + 1
                self._latest[oid] = (version, content)
                self.objects[f"{oid}@{version}"] = content
            live.append(f"{oid}@{version}")
        return live

    def latest(self, oid: str) -> Content | None:
        entry = self._latest.get(oid)
        return entry[1] if entry else None

    # --------------------------------------------------------------------------- internals

    def _oid(self, obj: object) -> str:
        key = id(obj)
        oid = self._ids.get(key)
        if oid is None:
            oid = f"o{len(self._ids) + 1}"
            self._ids[key] = oid
            self._keep.append(obj)
        return oid

    def _items(self, seq: Any, depth: int) -> tuple[list[Value], int]:
        n = len(seq)
        items = [self.value(x, depth + 1) for x in _take(seq, self.max_items)]
        return items, max(0, n - self.max_items)

    def _content(self, obj: object, depth: int) -> Content:
        tname = _type_name(obj)
        out: Content
        if isinstance(obj, tuple) and hasattr(obj, "_fields"):  # namedtuple
            fields = [[f, self.value(getattr(obj, f), depth + 1)] for f in obj._fields]
            out = {"type": tname, "shape": "record", "fields": fields}
        elif isinstance(obj, (list, tuple, deque)):
            items, more = self._items(obj, depth)
            out = {"type": tname, "shape": "sequence", "items": items}
            if more:
                out["more"] = more
        elif isinstance(obj, dict):
            entries = [
                [self.value(k, depth + 1), self.value(v, depth + 1)]
                for k, v in _take(obj.items(), self.max_items)
            ]
            out = {"type": tname, "shape": "mapping", "entries": entries}
            if len(obj) > self.max_items:
                out["more"] = len(obj) - self.max_items
        elif isinstance(obj, (set, frozenset)):
            items, more = self._items(obj, depth)
            out = {"type": tname, "shape": "set", "items": items}
            if more:
                out["more"] = more
        elif isinstance(obj, types.FunctionType):
            out = {"type": "function", "shape": "function", "repr": _signature(obj)}
        elif isinstance(obj, (types.BuiltinFunctionType, types.MethodType)):
            out = {
                "type": "function",
                "shape": "function",
                "repr": getattr(obj, "__qualname__", "?"),
            }
        elif isinstance(obj, type):
            out = {"type": "class", "shape": "class", "repr": obj.__qualname__}
        elif isinstance(obj, types.ModuleType):
            out = {"type": "module", "shape": "opaque", "repr": obj.__name__}
        elif hasattr(obj, "__dict__") or hasattr(type(obj), "__slots__"):
            out = {"type": tname, "shape": "record", "fields": self._fields(obj, depth)}
        else:
            out = {"type": tname, "shape": "opaque", "repr": _safe_repr(obj)}
        return out

    def _fields(self, obj: object, depth: int) -> list[list[Any]]:
        fields: list[list[Any]] = []
        # Read the instance dict directly: getattr() could run a user @property mid-snapshot.
        d = getattr(obj, "__dict__", None)
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(k, str) and not k.startswith("__"):
                    fields.append([k, v])
        for klass in type(obj).__mro__:
            slots = klass.__dict__.get("__slots__", ())
            if isinstance(slots, str):
                slots = (slots,)
            for name in slots:
                if name in ("__dict__", "__weakref__"):
                    continue
                try:  # slots are C-level descriptors: no user code runs
                    fields.append([name, getattr(obj, name)])
                except AttributeError:  # unset slot
                    continue
        return [[k, self.value(v, depth + 1)] for k, v in fields[: self.max_items]]


def _take(it: Any, n: int) -> list[Any]:
    out = []
    for i, x in enumerate(it):
        if i >= n:
            break
        out.append(x)
    return out


def _safe_repr(obj: object, limit: int = 80) -> str:
    try:
        text = repr(obj)
    except Exception:  # a broken __repr__ must not break the trace
        text = f"<{_type_name(obj)}>"
    return text if len(text) <= limit else text[:limit] + "…"


def compact(value: Value, lookup: Any, limit: int = 40, _depth: int = 0) -> str:
    """Short inline rendering of a value for captions, e.g. `[1, 3, 5, …]`."""
    if "p" in value:
        text = str(value["p"])
        return text if len(text) <= limit else text[: limit - 1] + "…"
    content = lookup(value["ref"]) if "ref" in value else None
    if content is None:
        return "…"
    shape = content["shape"]
    if _depth >= 3 and shape in ("sequence", "mapping", "set", "record"):
        return "…"

    def inner(v: Value) -> str:
        return compact(v, lookup, limit, _depth + 1)

    if shape == "sequence":
        body = ", ".join(inner(v) for v in content["items"][:8])
        if content.get("more") or len(content["items"]) > 8:
            body += ", …"
        text = f"({body})" if content["type"] == "tuple" else f"[{body}]"
    elif shape == "set":
        text = "{" + ", ".join(inner(v) for v in content["items"][:8]) + "}"
    elif shape == "mapping":
        pairs = ", ".join(f"{inner(k)}: {inner(v)}" for k, v in content["entries"][:6])
        text = "{" + pairs + "}"
    elif shape == "record":
        fields = ", ".join(f"{k}={inner(v)}" for k, v in content["fields"][:4])
        text = f"{content['type']}({fields})"
    elif shape == "function":
        text = f"function {content['repr']}"
    elif shape == "class":
        text = f"class {content['repr']}"
    else:
        text = str(content.get("repr", content["type"]))
    return text if len(text) <= limit else text[: limit - 1] + "…"
