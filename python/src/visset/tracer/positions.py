"""Map bytecode instructions to the source ranges a learner would point at.

CPython (3.11+) records, for every bytecode instruction, the source range it came from
(`code.co_positions()`). Those ranges are *too fine* for teaching: the first instruction of
`total += x` points at `total`, and the first instruction of `if arr[mid] < x:` points at `arr`.
So we parse the source once with `ast`, pick out the nodes a tutor would circle ("steppable"
nodes: statements, and the *header* of compound statements), and map each instruction to the
innermost steppable node that contains it.

Two unit systems meet here:
- `ast` and `co_positions()` use **UTF-8 byte** columns.
- The trace schema uses **Unicode code point** columns (language-neutral; see the schema docs).
Matching happens in bytes; conversion to code points happens only for output.
"""

from __future__ import annotations

import ast
import dis
from dataclasses import dataclass, field
from types import CodeType

# Instructions that exist for the interpreter, not the program. Their positions point at the
# `def` line, which would otherwise create a bogus "define function" step on every call.
_SKIP_OPS = frozenset(
    {"RESUME", "RETURN_GENERATOR", "MAKE_CELL", "COPY_FREE_VARS", "CACHE", "EXTENDED_ARG"}
)

Pos = tuple[int, int]  # (line, column)


@dataclass(eq=False, slots=True)
class StepNode:
    """A piece of source a step can focus on. Compared by identity."""

    kind: str  # AST class name: "Assign", "If", "For", ...
    focus_start: Pos  # code points
    focus_end: Pos
    match_start: Pos  # bytes; instructions inside this range belong to the node
    match_end: Pos
    text: str  # the focused source text, for captions
    mark: str  # default annotation shape
    body_lines: tuple[int, int] | None = None  # If/While/For: lines of the body
    else_lines: tuple[int, int] | None = None
    names: tuple[str, ...] = ()  # assignment targets / loop variables / defined name
    target: tuple[str, ...] | None = None  # ("attr", obj, name) / ("item", obj, key-expr)
    stmt_end: Pos | None = None  # compound statements: end of the whole statement (bytes)
    ast_node: ast.AST | None = field(default=None, repr=False)


@dataclass(slots=True)
class CodeTable:
    """Per-code-object lookup used on the hot path of the tracer."""

    node_at: dict[int, StepNode]  # instruction offset -> node
    boundaries: frozenset[int]  # offsets where a new step may begin
    starts: frozenset[int]  # boundaries that begin a node's run (not just a jump target)


class SourceIndex:
    def __init__(self, source: str, filename: str = "<visset>") -> None:
        self.source = source
        self.filename = filename
        self.lines = source.splitlines()
        self._line_bytes = [ln.encode("utf-8") for ln in self.lines]
        self.tree = ast.parse(source, filename)
        self.nodes: list[StepNode] = []
        self._by_line: dict[int, list[StepNode]] = {}
        self._tables: dict[int, CodeTable] = {}
        self._codes: list[CodeType] = []  # keep code objects alive so id() keys stay valid
        self._collect(self.tree)

    # ----------------------------------------------------------------- unit conversion

    def to_cp(self, line: int, byte_col: int) -> int:
        """UTF-8 byte column -> code point column on a 1-based line."""
        if line < 1 or line > len(self._line_bytes):
            return byte_col
        raw = self._line_bytes[line - 1]
        if len(raw) == len(self.lines[line - 1]):  # ASCII line: identical
            return byte_col
        return len(raw[:byte_col].decode("utf-8", errors="replace"))

    def segment(self, start: Pos, end: Pos) -> str:
        """Source text between two code point positions."""
        (l1, c1), (l2, c2) = start, end
        if l1 == l2:
            return self.lines[l1 - 1][c1:c2]
        parts = [self.lines[l1 - 1][c1:], *self.lines[l1 : l2 - 1], self.lines[l2 - 1][:c2]]
        return "\n".join(parts)

    # ----------------------------------------------------------------- node collection

    def _add(
        self,
        node: ast.AST,
        kind: str,
        focus: tuple[Pos, Pos],
        match: tuple[Pos, Pos],
        mark: str,
        **extra: object,
    ) -> None:
        (fl, fc), (fel, fec) = focus
        f_start = (fl, self.to_cp(fl, fc))
        f_end = (fel, self.to_cp(fel, fec))
        step = StepNode(
            kind=kind,
            focus_start=f_start,
            focus_end=f_end,
            match_start=match[0],
            match_end=match[1],
            text=self.segment(f_start, f_end),
            mark=mark,
            ast_node=node,
            **extra,  # type: ignore[arg-type]
        )
        self.nodes.append(step)
        for line in range(match[0][0], match[1][0] + 1):
            self._by_line.setdefault(line, []).append(step)

    @staticmethod
    def _span(node: ast.AST) -> tuple[Pos, Pos]:
        return (
            (node.lineno, node.col_offset),  # type: ignore[attr-defined]
            (node.end_lineno, node.end_col_offset),  # type: ignore[attr-defined]
        )

    @staticmethod
    def _lines(body: list[ast.stmt]) -> tuple[int, int] | None:
        if not body:
            return None
        return (body[0].lineno, body[-1].end_lineno or body[-1].lineno)

    def _header_end(self, line: int, byte_col: int) -> Pos:
        """Byte position just before the `:` that ends a compound-statement header."""
        depth = 0
        quote: str | None = None
        for ln in range(line, len(self._line_bytes) + 1):
            text = self._line_bytes[ln - 1].decode("utf-8", errors="replace")
            start = self.to_cp(ln, byte_col) if ln == line else 0
            i = start
            while i < len(text):
                ch = text[i]
                if quote:
                    if ch == "\\":
                        i += 1
                    elif ch == quote:
                        quote = None
                elif ch in "\"'":
                    quote = ch
                elif ch == "#":
                    break
                elif ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                elif ch == ":" and depth == 0:
                    end = len(text[:i].rstrip().encode("utf-8"))
                    return (ln, end)
                i += 1
        return (line, len(self._line_bytes[line - 1]))

    def _header(self, node: ast.stmt) -> tuple[Pos, Pos]:
        """Match range of a compound statement: its whole header, keyword to colon.

        The *focus* stays narrow (`lo <= hi`, `x in items`), but loop bookkeeping instructions
        point at different parts of the header across patch releases: on CPython 3.12.3
        `FOR_ITER` spans `for x in items`, on 3.12.13 just `items`. Matching the whole header
        keeps per-iteration steps on every version.
        """
        start = (node.lineno, node.col_offset)
        return start, self._header_end(*start)

    def _collect(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.While)):
                span = self._span(node.test)
                self._add(
                    node,
                    type(node).__name__,
                    span,
                    self._header(node),
                    "underline",
                    body_lines=self._lines(node.body),
                    else_lines=self._lines(node.orelse),
                    stmt_end=self._span(node)[1],
                )
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                span = (self._span(node.target)[0], self._span(node.iter)[1])
                self._add(
                    node,
                    "For",
                    span,
                    self._header(node),
                    "underline",
                    body_lines=self._lines(node.body),
                    else_lines=self._lines(node.orelse),
                    names=_target_names(node.target),
                    stmt_end=self._span(node)[1],
                )
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                first, last = node.items[0], node.items[-1]
                end_node = last.optional_vars or last.context_expr
                span = (self._span(first.context_expr)[0], self._span(end_node)[1])
                self._add(
                    node,
                    "With",
                    span,
                    self._header(node),
                    "underline",
                    stmt_end=self._span(node)[1],
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = (node.lineno, node.col_offset)
                header = (start, self._header_end(*start))
                full_start = min([start, *((d.lineno, d.col_offset) for d in node.decorator_list)])
                kind = "ClassDef" if isinstance(node, ast.ClassDef) else "FunctionDef"
                match = (full_start, self._span(node)[1])
                self._add(node, kind, header, match, "underline", names=(node.name,))
            elif isinstance(node, ast.ExceptHandler):
                start = (node.lineno, node.col_offset)
                header = (start, self._header_end(*start))
                self._add(node, "ExceptHandler", header, header, "underline")
            elif isinstance(node, ast.Match):
                span = self._span(node.subject)
                self._add(node, "Match", span, span, "underline")
            elif isinstance(node, (ast.Lambda, ast.GeneratorExp)):
                # These run in their own frames; give their steps a focus of their own.
                inner = node.body if isinstance(node, ast.Lambda) else node
                span = self._span(inner)
                self._add(node, type(node).__name__, span, span, "circle")
            elif isinstance(node, (ast.Try, ast.TryStar)):
                continue  # the `try:` line itself does nothing; its body statements step
            elif isinstance(node, ast.stmt):
                span = self._span(node)
                names: tuple[str, ...] = ()
                target_node: ast.AST | None = None
                if isinstance(node, ast.Assign):
                    names = tuple(n for t in node.targets for n in _target_names(t))
                    target_node = node.targets[0] if len(node.targets) == 1 else None
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    names = _target_names(node.target)
                    target_node = node.target
                self._add(
                    node,
                    type(node).__name__,
                    span,
                    span,
                    "circle",
                    names=names,
                    target=_simple_target(target_node),
                )

    # ----------------------------------------------------------------- instruction mapping

    def _match(
        self, line: int, end_line: int, col: int, end_col: int, own: StepNode | None = None
    ) -> StepNode | None:
        best: StepNode | None = None
        best_size: tuple[int, int] | None = None
        for node in self._by_line.get(line, ()):
            if node is own:
                continue
            if (line, col) < node.match_start or (end_line, end_col) > node.match_end:
                continue
            size = (
                node.match_end[0] - node.match_start[0],
                node.match_end[1] - node.match_start[1],
            )
            if best_size is None or size < best_size:
                best, best_size = node, size
        if best is None:
            # Loop bookkeeping (FOR_ITER, END_FOR...) on some patch releases spans the *whole*
            # compound statement, body included. It still belongs to the header's step.
            for node in self._by_line.get(line, ()):
                if (
                    node.stmt_end is not None
                    and (line, col) == node.match_start
                    and (end_line, end_col) <= node.stmt_end
                ):
                    return node
        return best

    def table(self, code: CodeType) -> CodeTable:
        """Build (once) the offset -> node table and the boundary set for a code object."""
        cached = self._tables.get(id(code))
        if cached is not None:
            return cached
        # A function's body never belongs to its own `def` step (only the code that runs the
        # `def` does), even when an instruction's position spans the whole function, as some
        # instructions do on CPython 3.12.3.
        own = next(
            (
                n
                for n in self.nodes
                if n.kind in ("FunctionDef", "ClassDef")
                and n.names == (code.co_name,)
                and n.match_start[0] <= code.co_firstlineno <= n.focus_start[0]
            ),
            None,
        )
        node_at: dict[int, StepNode] = {}
        boundaries: set[int] = set()
        starts: set[int] = set()
        prev: StepNode | None = None
        for ins in dis.get_instructions(code):
            pos = ins.positions
            if ins.opname in _SKIP_OPS or pos is None:
                continue
            if pos.lineno is None or pos.col_offset is None:
                continue
            if pos.lineno == pos.end_lineno and pos.col_offset == pos.end_col_offset:
                continue  # zero-width: synthetic
            node = self._match(
                pos.lineno,
                pos.end_lineno or pos.lineno,
                pos.col_offset,
                pos.end_col_offset or 0,
                own,
            )
            if node is None:
                continue
            node_at[ins.offset] = node
            # A step begins where a new node's run starts, or where control can jump in
            # (loop heads). Everything else will be DISABLEd after its first hit.
            if node is not prev:
                boundaries.add(ins.offset)
                starts.add(ins.offset)
            elif _is_jump_target(ins):
                boundaries.add(ins.offset)
            prev = node
        table = CodeTable(node_at, frozenset(boundaries), frozenset(starts))
        self._tables[id(code)] = table
        self._codes.append(code)
        return table


def _is_jump_target(ins: dis.Instruction) -> bool:
    # 3.12/3.13 expose `is_jump_target`; 3.14 derives it from `label`.
    target = getattr(ins, "is_jump_target", None)
    if target is not None:
        return bool(target)
    return getattr(ins, "label", None) is not None


def _simple_target(t: ast.AST | None) -> tuple[str, ...] | None:
    """`obj.attr` or `obj[key]` where key is a name or literal: things we can show by lookup."""
    if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name):
        return ("attr", t.value.id, t.attr)
    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
        key = t.slice
        if isinstance(key, ast.Name):
            return ("item", t.value.id, "name", key.id)
        if isinstance(key, ast.Constant) and isinstance(key.value, (int, str)):
            return ("item", t.value.id, "const", repr(key.value))
        if (
            isinstance(key, ast.UnaryOp)
            and isinstance(key.op, ast.USub)
            and isinstance(key.operand, ast.Constant)
            and isinstance(key.operand.value, int)
        ):
            return ("item", t.value.id, "const", repr(-key.operand.value))
    return None


def _target_names(target: ast.AST) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(n for elt in target.elts for n in _target_names(elt))
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Attribute, ast.Subscript)):
        root = target.value
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        return (root.id,) if isinstance(root, ast.Name) else ()
    return ()


_CO_OPTIMIZED = 0x0001  # set on function-like code objects, not on module or class bodies


def user_code_objects(code: CodeType, _root: bool = True) -> list[CodeType]:
    """The module code object and every function/lambda code object nested in it.

    Class *bodies* are skipped: they run once to build the class, and stepping through them
    ("call Node", "define __init__") confuses more than it teaches. Their methods are kept.
    """
    out = [code] if _root or code.co_flags & _CO_OPTIMIZED else []
    for const in code.co_consts:
        if isinstance(const, CodeType):
            out.extend(user_code_objects(const, _root=False))
    return out
