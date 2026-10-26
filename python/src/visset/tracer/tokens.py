"""Syntax-highlighting tokens for the player: `[line, col, endCol, kind]`, code point columns.

The tracer ships tokens with the source so the player needs no grammar for any language.
Only tokens that get a color are emitted, which keeps traces small.
"""

from __future__ import annotations

import builtins
import io
import keyword
import token
import tokenize

_BUILTINS = frozenset(n for n in dir(builtins) if not n.startswith("_"))
_CONSTANTS = frozenset({"True", "False", "None"})
_STRING_TYPES = {token.STRING}
for _name in (
    "FSTRING_START",
    "FSTRING_MIDDLE",
    "FSTRING_END",
    "TSTRING_START",
    "TSTRING_MIDDLE",
    "TSTRING_END",
):
    if hasattr(token, _name):
        _STRING_TYPES.add(getattr(token, _name))


def python_tokens(source: str) -> list[list[int | str]]:
    out: list[list[int | str]] = []
    prev: tokenize.TokenInfo | None = None
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return out
    for i, tok in enumerate(toks):
        kind: str | None = None
        if tok.type in _STRING_TYPES:
            kind = "string"
        elif tok.type == token.NUMBER:
            kind = "number"
        elif tok.type == token.COMMENT:
            kind = "comment"
        elif tok.type == token.NAME:
            if tok.string in _CONSTANTS:
                kind = "constant"
            elif keyword.iskeyword(tok.string) or (
                keyword.issoftkeyword(tok.string) and _soft_keyword_used(toks, i)
            ):
                kind = "keyword"
            elif prev is not None and prev.string in ("def", "class"):
                kind = "definition"
            elif tok.string in _BUILTINS:
                kind = "builtin"
            elif i + 1 < len(toks) and toks[i + 1].string == "(":
                kind = "call"
        if tok.type not in (token.NL, token.NEWLINE, token.INDENT, token.DEDENT):
            prev = tok
        if kind is None:
            continue
        (l1, c1), (l2, c2) = tok.start, tok.end
        if l1 == l2:
            out.append([l1, c1, c2, kind])
        else:  # multi-line string: one token per line
            lines = tok.string.split("\n")
            out.append([l1, c1, c1 + len(lines[0]), kind])
            for k, text in enumerate(lines[1:-1], start=1):
                out.append([l1 + k, 0, len(text), kind])
            out.append([l2, 0, c2, kind])
    return out


def _soft_keyword_used(toks: list[tokenize.TokenInfo], i: int) -> bool:
    # `match`, `case`, `type`, `_` are keywords only at the start of a statement.
    j = i - 1
    while j >= 0 and toks[j].type in (token.INDENT, token.DEDENT):
        j -= 1
    at_start = j < 0 or toks[j].type in (token.NEWLINE, token.NL)
    nxt = toks[i + 1] if i + 1 < len(toks) else None
    return (
        at_start
        and toks[i].string in ("match", "case", "type")
        and nxt is not None
        and nxt.type in (token.NAME, token.NUMBER, token.STRING, token.OP)
        and nxt.string not in ("=", ".", "(", ")", ",", ":")
    )
