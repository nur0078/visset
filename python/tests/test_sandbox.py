"""The sandboxed child process: limits must hold even against hostile-looking loops."""

from __future__ import annotations

import pytest

from visset.tracer import Limits, TraceError, TraceRequest, run_sandboxed


def sandboxed(src: str, **limits: int) -> tuple[dict, int]:
    return run_sandboxed(TraceRequest(src, path="t.py", limits=Limits(**limits)))


def test_round_trip_matches_in_process_semantics() -> None:
    trace, status = sandboxed("x = [1, 2]\nprint(len(x))\n")
    assert status == 0
    assert trace["steps"][-1]["stdout"] == "2\n"


def test_bare_except_cannot_swallow_the_step_limit() -> None:
    src = "while True:\n    try:\n        x = 1\n    except:\n        pass\n"
    trace, status = sandboxed(src, max_steps=25)
    assert status == 3
    assert trace["meta"]["truncated"]["reason"] == "maxSteps"


def test_infinite_recursion_stops_at_max_stack() -> None:
    trace, status = sandboxed("def f(n):\n    return f(n + 1)\nf(0)\n", max_stack=30)
    assert status == 3
    assert trace["meta"]["truncated"] == {"reason": "maxStack", "limit": 30}


@pytest.mark.skipif(not hasattr(__import__("signal"), "setitimer"), reason="no SIGALRM on Windows")
def test_sleeping_program_times_out_with_a_partial_trace() -> None:
    trace, status = sandboxed("import time\nx = 1\ntime.sleep(30)\n", timeout_ms=500)
    assert status == 3
    assert trace["meta"]["truncated"]["reason"] == "timeout"
    assert len(trace["steps"]) >= 2


@pytest.mark.skipif(__import__("sys").platform != "linux", reason="RLIMIT_AS is Linux-only")
def test_memory_limit() -> None:
    src = "x = 1\nblob = bytearray(2_000_000_000)\n"
    trace, status = sandboxed(src, memory_mb=200)
    assert status == 2
    assert trace["meta"]["error"]["type"] == "MemoryError"


def test_user_code_cannot_see_the_parent_environment() -> None:
    trace, _ = sandboxed("import os\nkeys = sorted(os.environ)\n")
    keys = trace["objects"][trace["steps"][-1]["heap"][0]]["items"]
    assert {"p": "'HOME'", "t": "str"} not in keys


def test_bad_args_are_a_clear_error() -> None:
    req = TraceRequest("def f(x):\n    return x\n", path="t.py", function="f", args="oops(")
    with pytest.raises(TraceError, match="Python literals"):
        run_sandboxed(req)
