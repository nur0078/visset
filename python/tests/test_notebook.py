"""Notebook display: `show()` and `to_html()` render the player under the cell."""

from __future__ import annotations

import html
from typing import Any

import pytest

import visset
from conftest import run
from test_cli import needs_player
from visset.export import html as export

pytestmark = needs_player

SOURCE = "total = 0\nfor x in [1, 2]:\n    total += x\n"


def test_notebook_html_is_a_frame_holding_the_whole_page() -> None:
    trace = run(SOURCE)
    out = export.render_notebook(trace, height=500)
    assert out.startswith('<iframe srcdoc="') and "height: 500px" in out
    srcdoc = out.split('srcdoc="', 1)[1].split('"', 1)[0]
    page = html.unescape(srcdoc)
    assert page == export.render_html(trace, embed=True)
    assert "<visset-player global-keys>" in page and "background: transparent" in page


def test_show_plays_inline_in_a_notebook(monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[dict[str, Any]] = []
    monkeypatch.setattr(export, "in_notebook", lambda: True)
    monkeypatch.setattr(export, "display_inline", lambda t: shown.append(t))
    monkeypatch.setattr(export, "open_in_browser", lambda t: pytest.fail("opened a browser"))
    trace = run(SOURCE)
    assert visset.show(trace) is None
    assert shown == [trace]


def test_show_opens_the_browser_outside_a_notebook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "in_notebook", lambda: False)
    monkeypatch.setattr(export, "open_in_browser", lambda t: "/tmp/x.html")
    assert visset.show(run(SOURCE)) == "/tmp/x.html"


def test_to_html_is_the_page_but_displays_as_the_player() -> None:
    trace = run(SOURCE)
    out = visset.to_html(trace)
    assert isinstance(out, str) and out == export.render_html(trace)
    bundle = out._repr_mimebundle_()  # type: ignore[attr-defined]
    assert bundle["text/html"].startswith("<iframe")
    assert bundle["text/plain"].startswith("<visset walkthrough")


def test_not_a_notebook_under_pytest() -> None:
    assert export.in_notebook() is False
