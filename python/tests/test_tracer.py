"""Behaviour of the Python tracer: state after each step, frames, captions, limits."""

from __future__ import annotations

from typing import Any

from conftest import EXAMPLES, captions, focused, run
from visset.tracer import Limits


def local(step: dict[str, Any], name: str, frame: int = -1) -> Any:
    return dict(step["stack"][frame]["locals"]).get(name)


def test_state_is_recorded_after_the_focused_code_runs() -> None:
    trace = run("x = 1\nx = x + 41\n")
    assert local(trace["steps"][0], "x") == {"p": "1", "t": "int"}
    assert local(trace["steps"][1], "x") == {"p": "42", "t": "int"}


def test_binary_search_walkthrough() -> None:
    trace = run((EXAMPLES / "bsearch.py").read_text())
    caps = captions(trace)
    assert "Call `binary_search(arr=[1, 3, 5, 7, 9, 11], target=7)`." in caps
    assert "`lo <= hi` is true, so the loop body runs." in caps
    assert "`arr[mid] == target` is false, so the next condition is checked." in caps
    assert "`binary_search` returns `3`." in caps
    assert caps[-1] == "Print `found at 3`."
    assert trace["steps"][-1]["stdout"] == "found at 3\n"


def test_recursion_builds_and_unwinds_the_call_stack() -> None:
    trace = run((EXAMPLES / "fib.py").read_text())
    depths = [len(s["stack"]) for s in trace["steps"]]
    assert max(depths) == 5  # Global + fib(4) -> fib(3) -> fib(2) -> fib(1)
    assert depths[-1] == 1
    returns = [s for s in trace["steps"] if s["kind"] == "return"]
    assert returns and all("returnValue" in s["stack"][-1] for s in returns)
    assert local(trace["steps"][-1], "result") == {"p": "3", "t": "int"}


def test_frames_keep_stable_ids_across_steps() -> None:
    trace = run("def f(a):\n    b = a\n    return b\nf(1)\n")
    ids = {s["stack"][-1]["id"] for s in trace["steps"] if s["stack"][-1]["name"] == "f"}
    assert len(ids) == 1


def test_object_versions_change_only_when_content_changes() -> None:
    trace = run("a = [1]\nb = 0\na.append(2)\nc = 0\n")
    heaps = [s["heap"] for s in trace["steps"]]
    assert heaps[0] == heaps[1]  # `b = 0` doesn't touch the list
    assert heaps[2] != heaps[1]  # append creates a new version
    assert heaps[2] == heaps[3]
    v0, v1 = heaps[1][0], heaps[2][0]
    assert v0.split("@")[0] == v1.split("@")[0]  # same object, new version
    assert len(trace["objects"][v1]["items"]) == 2


def test_aliasing_shares_one_object() -> None:
    trace = run("a = [1, 2]\nb = a\n")
    step = trace["steps"][-1]
    assert local(step, "a") == local(step, "b")
    assert "ref" in local(step, "a")


def test_nested_change_marks_the_outer_variable() -> None:
    src = (
        "class Node:\n    def __init__(self, v, nxt=None):\n        self.v = v\n"
        "        self.nxt = nxt\nhead = Node(1, Node(2))\nhead.nxt.v = 9\n"
    )
    assert captions(run(src))[-1].startswith("`head` is updated")


def test_attribute_and_index_assignment_captions() -> None:
    caps = captions(run("arr = [0, 0]\ni = 1\narr[i] = 5\nd = {}\nd['k'] = 2\n"))
    assert "`arr[1]` becomes `5`." in caps
    assert "`d['k']` becomes `2`." in caps


def test_class_bodies_are_not_stepped_but_methods_are() -> None:
    src = "class A:\n    def m(self):\n        return 1\nA().m()\n"
    trace = run(src)
    assert captions(trace)[0] == "Define the class `A`."
    assert "Call `A.m(self=A())`." in captions(trace)
    assert not any(s["stack"][-1]["name"] == "A" for s in trace["steps"])


def test_generators_yield_and_resume() -> None:
    src = "def g():\n    yield 1\n    yield 2\nout = list(g())\n"
    caps = captions(run(src))
    assert "`g` yields `1` and pauses." in caps
    assert "`g` yields `2` and pauses." in caps


def test_caught_exception_is_shown_where_it_was_raised() -> None:
    src = "try:\n    x = 1 / 0\nexcept ZeroDivisionError:\n    x = 0\n"
    trace = run(src)
    raised = next(s for s in trace["steps"] if s["kind"] == "exception")
    assert raised["focus"][0]["tone"] == "error"
    assert focused(trace)[trace["steps"].index(raised)] == "x = 1 / 0"
    assert "Catch the `ZeroDivisionError`." in captions(trace)
    assert trace["meta"]["error"] is None


def test_uncaught_exception_ends_the_trace_with_an_error() -> None:
    trace = run("def f(d):\n    return d['k']\nf({})\n")
    assert trace["meta"]["error"] == {"type": "KeyError", "message": "'k'", "line": 2}
    assert any(s["caption"] == "`KeyError: 'k'` is raised here." for s in trace["steps"])


def test_syntax_error_produces_a_one_step_trace() -> None:
    trace = run("x = (1,\n")
    assert trace["meta"]["error"]["type"] == "SyntaxError"
    assert len(trace["steps"]) == 1
    assert trace["steps"][0]["focus"][0]["tone"] == "error"


def test_stdout_is_a_per_step_delta_and_input_is_echoed() -> None:
    trace = run("print('a')\nname = input('who? ')\nprint(name)\n", stdin="Ada\n")
    outs = [s.get("stdout", "") for s in trace["steps"]]
    assert outs == ["a\n", "who? Ada\n", "Ada\n"]
    assert captions(trace)[1] == "`name` becomes `'Ada'`."


def test_entry_function_traces_only_that_call() -> None:
    src = "setup = 1\ndef sq(x):\n    return x * x\n"
    trace = run(src, function="sq", args="7")
    assert trace["meta"]["entry"] == "sq(7)"
    assert [s["stack"][0]["name"] for s in trace["steps"]] == ["sq"]
    assert trace["steps"][-1]["stack"][-1]["returnValue"] == {"p": "49", "t": "int"}


def test_max_steps_truncates_an_infinite_loop() -> None:
    trace = run("while True:\n    pass\n", limits=Limits(max_steps=20))
    assert len(trace["steps"]) == 20
    assert trace["meta"]["truncated"] == {"reason": "maxSteps", "limit": 20}


def test_large_containers_are_elided() -> None:
    trace = run("big = list(range(1000))\n", limits=Limits(max_items=10))
    obj = trace["objects"][trace["steps"][0]["heap"][0]]
    assert len(obj["items"]) == 10
    assert obj["more"] == 990


def test_cycles_do_not_hang_the_snapshot() -> None:
    trace = run("a = []\na.append(a)\n")
    obj = trace["objects"][trace["steps"][-1]["heap"][0]]
    assert obj["items"][0] == local(trace["steps"][-1], "a")


def test_properties_are_not_called_while_snapshotting() -> None:
    src = (
        "calls = []\nclass P:\n    @property\n    def x(self):\n        calls.append(1)\n"
        "        return 1\np = P()\nn = len(calls)\n"
    )
    assert local(run(src)["steps"][-1], "n") == {"p": "0", "t": "int"}


def test_tracing_twice_in_one_process_is_independent() -> None:
    a = run("x = 1\n")
    b = run("x = 1\n")
    assert a["steps"] == b["steps"]


def test_sets_of_objects_list_them_in_the_order_first_seen() -> None:
    # Iteration order of a set of objects depends on memory addresses; the trace must not.
    src = "class N:\n    pass\na, b, c = N(), N(), N()\ns = {c, a, b}\n"
    trace = run(src)
    objects = trace["objects"]
    ids = [dict(trace["steps"][-1]["stack"][0]["locals"])[n]["ref"] for n in "abcs"]
    s = next(v for k, v in objects.items() if k.startswith(ids[3] + "@"))
    assert [v["ref"] for v in s["items"]] == ids[:3]
