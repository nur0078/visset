"""Regenerate schema/fixtures/python-*.trace.json from examples/*.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import EXAMPLES, GOLDEN, run

for path in sorted(EXAMPLES.glob("*.py")):
    trace = run(path.read_text(), path=path.name)
    trace["meta"]["runtime"] = "CPython"
    trace["meta"]["generator"] = "visset"
    out = GOLDEN / f"python-{path.stem}.trace.json"
    out.write_text(json.dumps(trace, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(GOLDEN.parent.parent)} ({len(trace['steps'])} steps)")
