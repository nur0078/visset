from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from visset.tracer import Limits, TraceRequest, execute

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
SCHEMA = ROOT / "schema" / "trace.schema.json"
GOLDEN = ROOT / "schema" / "fixtures"


def run(source: str, **kw: Any) -> dict[str, Any]:
    """Trace in-process (fast) and return the trace."""
    kw.setdefault("limits", Limits())
    kw.setdefault("path", "t.py")
    trace, _status = execute(TraceRequest(source, **kw))
    return trace


def focused(trace: dict[str, Any]) -> list[str]:
    """The exact source text circled at each step."""
    lines = trace["sources"][0]["text"].splitlines()
    out = []
    for step in trace["steps"]:
        mark = step["focus"][0]
        (l1, c1), (l2, c2) = mark["start"], mark["end"]
        out.append(lines[l1 - 1][c1:c2] if l1 == l2 else f"<lines {l1}-{l2}>")
    return out


def captions(trace: dict[str, Any]) -> list[str]:
    return [s["caption"] for s in trace["steps"]]


@pytest.fixture(scope="session")
def validator() -> Any:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)
