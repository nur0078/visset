"""Visualizing part of the code: one function, a line range, a snippet, a live call."""

from __future__ import annotations

from typing import Any

import pytest

import visset
from conftest import EXAMPLES, captions, focused, run
from visset.tracer import TraceError

TWO_POINTERS = (EXAMPLES / "two_pointers.py").read_text()


def is_palindrome(text: str) -> bool:
    left, right = 0, len(text) - 1
    while left < right:
        if text[left] != text[right]:
            return False
        left += 1
        right -= 1
    return True


class Stack:
    def __init__(self) -> None:
        self.items: list[Any] = []

    def push(self, item: Any) -> None:
        self.items.append(item)


def shown_lines(trace: dict[str, Any]) -> tuple[int, int]:
    src = trace["sources"][0]
    first = src.get("firstLine", 1)
    return first, first + len(src["text"].splitlines()) - 1


def test_fn_shows_only_that_function(validator: Any) -> None:
    trace = run(TWO_POINTERS, function="is_palindrome", args='"level"')
    assert shown_lines(trace) == (1, 9)
    assert trace["sources"][0]["text"].startswith("def is_palindrome(text):")
    assert validator.is_valid(trace)


def test_fn_hides_steps_in_other_functions() -> None:
    # longest_palindrome calls is_palindrome; with --fn longest_palindrome only its own lines
    # are shown, and the helper call is a single step.
    trace = run(TWO_POINTERS, function="longest_palindrome", args='["noon", "ab"]')
    first, last = shown_lines(trace)
    assert (first, last) == (12, 17)
    assert "left, right = 0, len(text) - 1" not in focused(trace)
    assert "Call `is_palindrome(text='noon')`." in captions(trace)


def test_dotted_fn_traces_a_method() -> None:
    src = "class Box:\n    def put(self, x):\n        self.x = x\n        return x\n"
    src += "def unused():\n    pass\n"
    trace = run("box = None\n" + src, function="Box.put", args="Box(), 5")
    assert focused(trace) == ["self.x = x", "return x"]
    assert shown_lines(trace) == (3, 5)  # line 1 is `box = None`


def test_lines_window_renumbers_and_keeps_context(validator: Any) -> None:
    trace = run(TWO_POINTERS, lines=(4, 8))
    assert shown_lines(trace) == (4, 8)
    assert trace["meta"]["title"] == "t.py, lines 4–8"
    assert set(focused(trace)) <= {
        "left < right",
        "text[left] != text[right]",
        "left += 1",
        "right -= 1",
        "return False",
    }
    # Every focus is inside the excerpt, and the full call stack is still there for context.
    n = len(trace["sources"][0]["text"].splitlines())
    assert all(1 <= s["focus"][0]["start"][0] <= n for s in trace["steps"])
    assert {f["name"] for s in trace["steps"] for f in s["stack"]} >= {"Global", "is_palindrome"}
    assert not list(validator.iter_errors(trace))


def test_output_from_hidden_steps_is_not_lost() -> None:
    trace = run("print('before')\nx = 1\nprint('after')\n", lines=(2, 2))
    assert [s.get("stdout", "") for s in trace["steps"]] == ["before\nafter\n"]


def test_lines_outside_any_code_give_an_empty_trace() -> None:
    assert run("x = 1\n\n\ny = 2\n", lines=(2, 3))["steps"] == []


def test_lines_past_the_end_is_a_clear_error() -> None:
    with pytest.raises(TraceError, match="past the end"):
        run("x = 1\n", lines=(5, 9))


def test_snippet_with_given_inputs() -> None:
    snippet = "total = 0\nfor x in xs:\n    total += x\n"
    trace = run(snippet, given="xs=[4, 5]")
    assert trace["meta"]["entry"] == "given xs=[4, 5]"
    assert captions(trace)[0] == "`total` becomes `0`."  # xs was there before: not a change
    assert trace["steps"][0]["changes"] == ["f1.total"]


def test_bad_given_is_a_clear_error() -> None:
    with pytest.raises(TraceError, match="name=value"):
        run("x = 1\n", given="[1, 2]")


def test_first_step_does_not_report_arguments_as_changes() -> None:
    trace = run(TWO_POINTERS, function="is_palindrome", args='"abba"')
    assert captions(trace)[0] == "`left` becomes `0`, `right` becomes `3`."


def test_live_call_shows_only_the_function() -> None:
    trace = visset.trace(is_palindrome, "kayak")
    assert trace["sources"][0]["text"].lstrip().startswith("def is_palindrome")
    assert trace["meta"]["entry"] == "is_palindrome('kayak')"
    assert trace["steps"][-1]["stack"][-1]["returnValue"] == {"p": "True", "t": "bool"}
    assert shown_lines(trace)[0] > 1  # real line numbers from this test file


def test_live_call_accepts_any_objects_and_methods() -> None:
    stack = Stack()
    trace = visset.trace(stack.push, {1, 2})  # a set: not something --args could express
    assert captions(trace) == ["`self` is updated to `Stack(items=[{1, 2}])`."]


def test_live_call_with_line_window() -> None:
    import inspect

    start = inspect.getsourcelines(is_palindrome)[1]
    trace = visset.trace_call(is_palindrome, ("noon",), lines=(start + 3, start + 5))
    assert set(focused(trace)) == {"text[left] != text[right]", "left += 1"}


def test_live_call_rejects_builtins() -> None:
    with pytest.raises(TraceError, match="not a Python function"):
        visset.trace(len, [1, 2])


def test_trace_source_dedents_a_pasted_fragment() -> None:
    fragment = """
        mid = (lo + hi) // 2
        hi = mid - 1
    """
    trace = visset.trace(fragment, given={"lo": 0, "hi": 6}, sandbox=False)
    assert focused(trace) == ["mid = (lo + hi) // 2", "hi = mid - 1"]
