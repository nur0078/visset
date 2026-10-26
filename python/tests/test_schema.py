"""Every trace we produce must satisfy the language-neutral schema, and stay stable.

Golden traces in schema/fixtures/ double as conformance fixtures for other tracers and the
player. When a change to the tracer is intended, regenerate them with:

    uv run python tests/update_goldens.py
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from conftest import EXAMPLES, GOLDEN, run

EXAMPLE_FILES = sorted(EXAMPLES.glob("*.py"))


def normalized(trace: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(trace))
    out["meta"].pop("runtime", None)
    out["meta"].pop("generator", None)
    return out


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_examples_validate(path: Any, validator: Any) -> None:
    trace = run(path.read_text(), path=path.name)
    errors = sorted(validator.iter_errors(trace), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:5])


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_examples_match_golden_traces(path: Any) -> None:
    golden = GOLDEN / f"python-{path.stem}.trace.json"
    assert golden.exists(), f"missing {golden.name}; run tests/update_goldens.py"
    expected = json.loads(golden.read_text())
    assert normalized(run(path.read_text(), path=path.name)) == normalized(expected)


@pytest.mark.parametrize(
    "src",
    [
        "x = (1,\n",  # syntax error
        "def f():\n    raise ValueError('no')\nf()\n",
        "import collections\nd = collections.deque([1])\ns = {1, 2}\nf = frozenset()\n",
        "class S:\n    __slots__ = ('a',)\ns = S()\ns.a = 1\n",
        "import enum\nclass C(enum.Enum):\n    R = 1\nc = C.R\n",
        "n = 10 ** 5000\n",
        "while True:\n    pass\n",
    ],
)
def test_edge_cases_validate(src: str, validator: Any) -> None:
    from visset.tracer import Limits

    trace = run(src, limits=Limits(max_steps=10))
    errors = list(validator.iter_errors(trace))
    assert not errors, errors[0].message


def test_every_heap_reference_resolves(validator: Any) -> None:
    trace = run((EXAMPLES / "fib.py").read_text())
    for step in trace["steps"]:
        live = {v.split("@")[0]: v for v in step["heap"]}
        assert all(v in trace["objects"] for v in step["heap"])
        for frame in step["stack"]:
            for _, value in frame["locals"]:
                if "ref" in value:
                    assert value["ref"] in live
