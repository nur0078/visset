"""Column-precise focus ranges: the exact expression, not the whole line."""

from __future__ import annotations

from conftest import focused, run
from visset.tracer.positions import SourceIndex


def test_two_statements_on_one_line_are_two_steps() -> None:
    # sys.monitoring's LINE event fires once per line; we must still split statements.
    assert focused(run("i = 0; i += 1\n")) == ["i = 0", "i += 1"]


def test_loop_and_branch_headers_focus_the_condition_only() -> None:
    src = "lo, hi = 0, 3\nwhile lo <= hi:\n    if lo > 1:\n        break\n    lo += 1\n"
    texts = focused(run(src))
    assert "lo <= hi" in texts
    assert "lo > 1" in texts
    assert "while lo <= hi:" not in texts


def test_for_header_focuses_target_and_iterable() -> None:
    assert focused(run("for x in [1, 2]:\n    y = x\n"))[:2] == ["x in [1, 2]", "y = x"]


def test_unicode_columns_are_code_points_not_bytes() -> None:
    # 'café' is 5 bytes in UTF-8 but 4 code points; columns after it must not drift.
    src = 'café = "naïve"; ü = café[0]\n'
    assert focused(run(src)) == ['café = "naïve"', "ü = café[0]"]


def test_byte_to_code_point_conversion() -> None:
    idx = SourceIndex("s = 'ü'; t = 1\n")
    # 'ü' is two bytes, so byte column 10 ("t") is code point column 9.
    assert idx.to_cp(1, 10) == 9
    assert idx.to_cp(1, 3) == 3


def test_def_focuses_the_signature_not_the_body() -> None:
    src = "def add(a,\n        b):\n    return a + b\n"
    first = run(src)["steps"][0]["focus"][0]
    assert first["start"] == [1, 0]
    assert first["end"] == [2, 10]


def test_lambda_steps_focus_the_lambda_body() -> None:
    texts = focused(run("f = lambda a: a * 2\nr = f(3)\n"))
    assert "a * 2" in texts


def test_comprehension_is_one_step_not_one_per_item() -> None:
    texts = focused(run("sq = [x * x for x in range(50)]\n"))
    assert texts == ["sq = [x * x for x in range(50)]"]


def test_one_line_loop_body_is_a_step_per_iteration() -> None:
    texts = focused(run("n = 0\nwhile n < 3: n += 1\n"))
    assert texts.count("n += 1") == 3
