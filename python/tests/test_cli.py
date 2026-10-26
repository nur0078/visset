from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import EXAMPLES
from visset.cli import main
from visset.export.html import PlayerMissingError, player_js, render_html


def has_player() -> bool:
    try:
        player_js()
    except PlayerMissingError:
        return False
    return True


needs_player = pytest.mark.skipif(not has_player(), reason="player bundle not built (pnpm build)")


def test_trace_command_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "t.json"
    assert main(["trace", str(EXAMPLES / "bsearch.py"), "-o", str(out)]) == 0
    trace = json.loads(out.read_text())
    assert trace["schema"] == "visset.trace/0.1"
    assert trace["meta"]["title"] == "bsearch.py"


def test_fn_and_args(tmp_path: Path) -> None:
    out = tmp_path / "t.json"
    args = [
        "trace",
        str(EXAMPLES / "bsearch.py"),
        "--fn",
        "binary_search",
        "--args",
        "[2, 4, 6], 6",
        "-o",
        str(out),
    ]
    assert main(args) == 0
    trace = json.loads(out.read_text())
    assert trace["steps"][-1]["stack"][-1]["returnValue"] == {"p": "2", "t": "int"}


def test_missing_file_is_a_clean_error() -> None:
    with pytest.raises(SystemExit, match="cannot read"):
        main(["run", "does-not-exist.py", "-o", "x.html"])


@needs_player
def test_run_exports_self_contained_html(tmp_path: Path) -> None:
    out = tmp_path / "walk.html"
    assert main(["run", str(EXAMPLES / "bsearch.py"), "-o", str(out)]) == 0
    html = out.read_text()
    assert "<visset-player" in html
    assert "customElements" in html  # the player is inlined, no network needed
    assert "http://" not in html.split("<script>")[0]


@needs_player
def test_html_escapes_script_terminators() -> None:
    from visset.tracer import TraceRequest, execute

    trace, _ = execute(TraceRequest("s = '</script><b>x</b>'\n", path="t.py"))
    html = render_html(trace)
    body = html.split('<script type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "</script" not in body
    assert json.loads(body)["steps"][0]["stack"][0]["locals"][0][1]["p"] == "'</script><b>x</b>'"


def test_cli_startup_is_fast() -> None:
    # "Snappy like matplotlib": --help must not import the tracer or exporter.
    code = "import sys, visset.cli; print(sorted(m for m in sys.modules if m.startswith('visset')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "['visset', 'visset._version', 'visset.cli']"
