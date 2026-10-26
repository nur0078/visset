# visset guide

## Python API

```python
import visset

visset.show(binary_search, [1, 3, 5, 7], 5)        # trace one call and show it (inline in a notebook)
trace = visset.trace(binary_search, [1, 3, 5, 7], 5)   # the trace as a dict (JSON-ready)
visset.to_html(trace, "bsearch.html")             # one self-contained HTML file
```

| Function | What it does |
|---|---|
| `trace(fn, *args, **kwargs)` | Calls `fn` and records only that call. The code pane shows only `fn`. |
| `trace_call(fn, args, kwargs, *, lines=None, limits=None, title=None)` | Same, with options. `lines=(4, 9)` shows only those lines of the file. |
| `trace(source, **options)` / `trace_source(...)` | Runs source text. Options: `given`, `function`, `args`, `lines`, `stdin`, `limits`, `sandbox`. |
| `show(fn_or_source_or_trace, ...)` | Like `trace`, then shows the result: under the cell in a notebook (returns `None`), otherwise in the browser (returns the HTML path). |
| `to_html(trace, path=None)` | Renders a trace to standalone HTML. In a notebook, the result displays as the player, not as text. |

A live call (`trace(fn, ...)`) runs in your Python process, because real objects can't cross a
process boundary, so its arguments can be anything. Use it on code you trust to finish; the step
and recursion limits still apply. Source text runs in the sandbox by default.

Functions typed into stdin or some REPLs have no saved source and can't be traced; define them in
a file or a notebook cell, or pass the code as a string.

## Command line

```bash
visset run file.py --fn binary_search --args "[1, 3, 5, 7], 5"   # one function call
visset run file.py --fn Stack.push --args "Stack(), 4"           # a method
visset run file.py --lines 4-9                     # part of a function (the program still runs)
visset run snippet.py --given "arr=[1, 3, 5], target=3"   # a fragment with inputs
visset run file.py                                 # the whole program
visset run file.py -o walkthrough.html             # write HTML instead of opening a browser
visset trace file.py -o file.trace.json            # the raw trace (JSON)
visset render file.trace.json -o out.html          # trace JSON -> HTML
```

- `--args` and `--given` are Python expressions evaluated in the program's own namespace, so they
  can use classes the file defines.
- With `--fn`, calls into other functions appear as single steps ("Call `helper(x=1)`" …
  "Back in `fn`: `helper` returned `2`").
- With `--lines`, steps outside the range run but are hidden; anything they print is kept.
- Limits: `--max-steps` (default 10,000), `--timeout` (default 5 s), `--stdin TEXT` for `input()`.

## The player

Keys: <kbd>←</kbd> <kbd>→</kbd> step, <kbd>Space</kbd> play/pause, <kbd>Home</kbd> <kbd>End</kbd>
jump, <kbd>[</kbd> <kbd>]</kbd> speed.

`<visset-player>` is a dependency-free web component (about 20 kB gzipped) you can embed anywhere:

```html
<script src="visset-player.js"></script>
<visset-player src="bsearch.trace.json" theme="auto"></visset-player>
```

Load a trace with `src`, an inline `<script type="application/json">` child, or the `.trace`
property. Control it with `goTo(i)`, `play()`, `pause()` and `setSpeed(x)`, and listen for
`stepchange` events. It follows the system light/dark setting (or `theme="light|dark"`) and
honors `prefers-reduced-motion`.

## Safety

Source runs in a child process with CPU-time, memory, wall-clock and step limits, an isolated
interpreter (`python -I`) and a minimal environment. That protects against *accidents* (infinite
loops, runaway recursion, huge allocations), **not against malicious code**: the program can still
read your files and use the network. Only trace code you would run yourself. On Windows only the
time and step limits apply. Live calls (`visset.trace(fn, ...)`) run in your own process.

## Limitations

- Python 3.12+ only (`sys.monitoring`).
- Only the main thread is recorded.
- Generators work; `async` code runs but isn't stepped through meaningfully yet.
- C extensions (numpy etc.) are opaque: you see the value's `repr`, not its insides.
- Big data is cut off: 50 items per container, nesting depth 8, 100 nested calls, 10,000 steps
  (all configurable).
- The tracer keeps references to every object it has shown, so `__del__` and weakref callbacks
  may run later than in a normal run.
