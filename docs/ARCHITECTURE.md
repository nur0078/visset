# visset — architecture proposal (v0.1, for review)

> Status: **accepted**, with refinements from probing CPython (§4). Updated as milestones land.

## 0. Decisions from the Q&A

| Question | Decision | Consequence |
|---|---|---|
| Audience | Learners & teachers, snippets of 5–200 lines | Hard limits (10k steps, 50 items per container) are fine; polish beats scale |
| Install | **Python-first**: `pip install visset` / `uvx visset`. `npx visset` added in M4 | Python core has **zero runtime deps** for trace + HTML export |
| Python | 3.12+ (`sys.monitoring`) | One code path. Older versions get a clear error message |
| Authoring | YAML + text selectors | `circle: "arr[mid]"` survives small edits to the code |
| Name | `visset` (package, CLI, element `<visset-player>`) | `codeviz` is too generic |
| Workflow | One branch + PR per milestone, CI on every PR | `main` always works |
| Scope | No features beyond the brief for now | Speed first: "snappy like matplotlib" |

**"Is there a faster language for the CLI?"** Rust or Go would give a single fast binary, but they wouldn't make
visset faster. The slow work is running and recording the user's program, and that has to happen *inside the
target language's own runtime*: a Python tracer must be Python, a JS tracer must talk to V8. The CLI only
orchestrates (start up, spawn, write a file), and Python starts in about 40 ms. A Rust CLI would add a third
language to maintain without speeding up any step that matters. The polish people see comes from the renderer,
which is TypeScript either way. So: **Python CLI and library, TypeScript renderer**, plus a thin `npx` front-end
that reuses the same renderer bundle and schema.

## 1. The core idea

```
 ┌────────────┐   ┌────────────┐   ┌──────────────┐
 │ Python     │   │ JS tracer  │   │ YAML author  │   ... DAP tracer (C/Go/Rust), AI author
 │ tracer     │   │ (V8/CDP)   │   │ compiler     │
 └─────┬──────┘   └─────┬──────┘   └──────┬───────┘
       └───────── one JSON Trace (schema/trace.schema.json) ─────────┘
                                │
                     <visset-player> web component
           (code pane + annotations + diagram + controls)
                                │
           HTML export · GIF/MP4/PNG export · playground · docs · VS Code
```

Rule of thumb: **tracers handle semantics, the renderer only draws.** The renderer never knows what a Python `list`
or a JS `Map` is. It sees language-neutral *shapes* (`sequence`, `mapping`, `record`, `set`, `opaque`) plus a
display string. That is what makes "add a language = write a tracer" true.

## 2. Repo layout (monorepo)

```
visset/
├── schema/                     # THE contract. Versioned independently.
│   ├── trace.schema.json       # JSON Schema (draft 2020-12)
│   ├── walkthrough.schema.json # authoring YAML schema (M3)
│   └── fixtures/*.trace.json   # golden traces; both Python and TS tests validate them
├── packages/                   # pnpm workspace (TypeScript)
│   ├── player/                 # @visset/player: <visset-player> web component (M1)
│   ├── tracer-js/              # V8 tracer (M4)
│   ├── cli-npm/                # `npx visset` (M4)
│   └── playground/             # web playground (M7)
├── python/                     # uv project → PyPI package `visset`
│   ├── src/visset/
│   │   ├── tracer/             # sys.monitoring tracer + sandbox runner
│   │   ├── schema.py           # typed models (dataclasses) mirroring the JSON schema
│   │   ├── author/             # YAML → Trace compiler (M3)
│   │   ├── structure/          # tree-sitter static diagrams (M6, extra)
│   │   ├── export/             # html (M1), frames/gif/mp4 (M6, extra)
│   │   ├── ai/                 # providers (M8, extra)
│   │   ├── cli.py
│   │   └── _assets/player.js   # built from packages/player, shipped as package data
│   └── tests/
├── examples/                   # bsearch.py, fib.py, linked_list.py, *.visset.yaml
└── docs/
```

**Why a monorepo:** the schema is the contract between three or four codebases. Keeping them in one repo means one PR
changes the schema, the tracers and the renderer together, and the golden fixtures catch any drift in CI.

**Why ship the built JS inside the Python wheel:** `pip install visset` then works offline with no Node. HTML export
is just "inline player.js + the trace JSON into a template".

## 3. Trace schema (v0.1)

### Conventions (where tools usually disagree)
- **Lines are 1-based. Columns are 0-based, end-exclusive, counted in Unicode code points.**
  *Why:* Python's AST reports columns in UTF-8 *bytes*, while JavaScript strings index in UTF-16 *units*. A
  string like `"héllo"[0]` would put the circle in the wrong place in one language or the other. Code points are
  the neutral unit, so each tracer converts on the way out and the renderer converts on the way in.
- Each step stores the state **after** the focused code ran ("what that code just did").

### Shape

```jsonc
{
  "schema": "visset.trace/0.1",
  "meta": {
    "language": "python", "runtime": "CPython 3.13.1", "generator": "visset-py 0.1.0",
    "origin": "traced",                      // traced | authored | mixed
    "title": "Binary search",
    "truncated": null                        // or {"reason": "max_steps", "limit": 10000}
  },
  "sources": [{
    "id": "main", "path": "bsearch.py", "text": "def search(arr, x):\n  ...",
    "tokens": [[1, 0, 3, "keyword"], [1, 4, 10, "function"]]   // optional: line, col, endCol, kind
  }],
  "objects": {                               // versioned heap-object pool (see "Why" below)
    "o1@0": { "type": "list", "shape": "sequence",
              "items": [{"p": "1", "t": "int"}, {"p": "3", "t": "int"}] },
    "o2@0": { "type": "Node", "shape": "record",
              "fields": [["val", {"p": "5", "t": "int"}], ["next", {"ref": "o3"}]] }
  },
  "steps": [{
    "kind": "statement",                     // statement | expression | call | return | exception | note
    "focus": [{
      "source": "main", "start": [6, 11], "end": [6, 19],  // [line, col] → circles `arr[mid]`
      "mark": "circle"                       // circle | underline | box | bracket | highlight | arrow | strike
    }],
    "caption": "Look at the middle element: arr[2] is 5.",
    "captionOrigin": "template",             // template | author | ai
    "stack": [{
      "id": "f1", "name": "search", "line": 6,
      "locals": [["arr", {"ref": "o1"}], ["lo", {"p": "0", "t": "int"}], ["mid", {"p": "2", "t": "int"}]]
    }],
    "heap": ["o1@0"],                        // object versions alive at this step
    "stdout": "Found\n",                     // output printed *during* this step (delta; the player sums them)
    "changes": ["f1.mid"],                   // optional; the renderer diffs consecutive steps if omitted
    "links": [{"focus": 0, "to": "o1[2]"}],  // optional connector arrows: code → diagram element
    "hints": {"o1": "array", "lo": "pointer:o1"}  // optional renderer hints
  }]
}
```

Value encoding: `{"p": display, "t": typeName}` for primitives (display is a string, so big ints and floats
survive JSON), and `{"ref": objectId}` for references. Diagram element paths follow a tiny grammar: `f1.mid`
(local), `o1[2]` (item), `o2.next` (field), `o4{"k"}` (map key).

**Why a versioned object pool instead of a full heap snapshot per step:** at 10k steps × 50 objects, full snapshots
would make a 50 MB HTML file. A tracer instead stores a new version of an object (`o1@3`) only when its content
changes, and each step lists which versions are alive. Any step can still be shown directly, with nothing to
replay from the start, and an unchanged array costs nothing per step. (This is the idea behind persistent data
structures.)

**Why the renderer, not the tracer, computes `changes` by default:** diffing two snapshots is language-neutral,
so every tracer gets change highlighting for free. Authored steps can still list `changes` explicitly.

Hand-authored steps use **the same schema**, so the renderer never needs to know whether a step was traced or written by hand.

## 4. Tracer interface

A tracer is **any executable** that reads a `TraceRequest` (JSON) on stdin and writes a `Trace` (JSON) to the `output` path in the request. The user program owns stdout and stderr, so the trace never shares a stream with the program's own `print` output.
Tracer diagnostics go to a log file. Exit codes: 0 = ok, 2 = user code raised (the trace is still valid and ends at the
exception), 3 = a limit was hit (the trace is still valid and truncated), 1 = tracer failure.

```jsonc
// TraceRequest
{ "source": {"path": "bsearch.py", "text": "..."},
  "entry": {"function": "search", "args": "[1,3,5,7,9], 7"},   // null = run the module top level
  "granularity": "statement",                                  // statement | expression
  "stdin": "",
  "limits": {"maxSteps": 10000, "timeoutMs": 5000, "memoryMb": 256, "maxItems": 50, "maxDepth": 8} }
```

**Why a process protocol instead of an in-process plugin API:** tracers can then be written in their own
language (the JS tracer in TypeScript, a Go tracer in Go), and the process boundary *is* the sandbox boundary.

### Python tracer (M1): `sys.monitoring`
I probed CPython 3.13, and it shows why this needs care:
- `LINE` fires **once per line, not per statement**: `i = 0; i += 1` would be one step.
- The instruction's position is its *first sub-expression* (`arr`), not the statement.

So the tracer:
1. Parses the source with `ast` (stdlib; no tree-sitter needed for Python) and builds, per code object,
   a table mapping bytecode offset → the innermost "steppable" node, using `code.co_positions()`.
2. Enables `INSTRUCTION` events **locally**, only on code objects compiled from the user's file (found by
   walking `co_consts` recursively). Library code isn't monitored at all.
3. Marks a small set of **boundary offsets** per code object: the first instruction of each node's run, plus
   jump targets (loop heads). Every other offset returns `DISABLE` the first time it fires, so it never fires
   again. In a probe, a loop whose instructions were all disabled ran at untraced speed (0.0283 s vs 0.0279 s).
   You pay only for the instructions that start a step.
4. Emits a step at each boundary that changes the node, or loops back to it. For `while`/`if`/`for`, the focus
   is the *header* (`lo <= hi`, `x in arr`), not the whole block.
5. Snapshots frames and heap (reachable from locals, BFS, with `maxItems` and `maxDepth` caps) and interns
   object versions.
6. Writes template captions: "`mid` becomes 2", "Call `fib(n=3)`", "`fib` returns 1", "`lo <= hi` is true → enter the loop".

Limits (steps, time) **end the child process with the trace written**, rather than raising an exception: the
probe showed that exceptions raised in a monitoring callback reach the user's code, where a user's
`except Exception:` would swallow them.

*Why `sys.monitoring` over `sys.settrace`:* per-code-object event control (library code is truly free), lower
overhead, and real instruction events. *Why not DAP for Python:* DAP stops at lines and returns variables as
display strings over many round-trips. That is slow, it loses object identity (you can't draw "two variables
point to the same list"), and it needs `debugpy`.

### Where DAP *does* fit
DAP is the right generic answer for **compiled languages** (C/C++/Rust via `lldb-dap`, Go via `delve`), where
running a tracer inside the program isn't possible. A future `tracer-dap` speaks DAP and maps `stackTrace`,
`scopes` and `variables` onto the schema. It is honest about the limits: stop locations are often line-only,
values are strings, and heap identity comes only from pointer values. That is why it isn't the main path.

### JS tracer (M4)
Run a `node --inspect-brk` child and drive it over the Chrome DevTools Protocol (`Debugger.stepInto`,
`Runtime.getProperties`). CDP pause locations include `columnNumber`, and `objectId` gives real heap identity.
The alternative is AST instrumentation (inject `__step(id, () => locals)`), which is faster but rewrites the
user's code and makes closures and scoping tricky. I'll prototype CDP first and decide at M4.

## 5. Renderer: `<visset-player>`

- **Vanilla TypeScript Web Component** (Shadow DOM, no framework). *Why:* it can be embedded anywhere (static HTML,
  docs sites, VS Code webviews, notebooks), it doesn't conflict with a host page's React or Vue, and the bundle stays
  small (target < 60 kB gzipped). Built with **esbuild** into a single file.
- **Code pane:** a custom read-only view, not Monaco or CodeMirror (hundreds of kB for features we don't use). It
  uses the `tokens` the tracer sends for syntax colors, so there are no grammars in the browser.
- **Annotations: Rough.js** drawing into an SVG overlay. The token range is measured with
  `Range.getClientRects()`, and the mark is drawn with a stroke-dashoffset "pen" animation.
  *Why Rough.js over rough-notation:* rough-notation annotates whole DOM elements and wraps badly across lines. We
  need exact sub-line ranges, and **seeded** randomness so a circle doesn't wobble differently every time you revisit a step.
- **Diagram:** SVG. A **stable custom layout** for stack and heap (frames on the left, objects in columns by
  reference depth). *Why not a generic graph layout for the heap:* stability matters more than optimality for
  learners. If objects jump around between steps, the animation lies. `d3-hierarchy` is for trees (M5).
  **ELK.js is loaded lazily**, only for control-flow and call graphs (M6), because it's about 1 MB.
- **Animation:** the FLIP technique with the Web Animations API (no animation library). Changed elements get
  an accent pulse. `prefers-reduced-motion` turns this into instant cross-fades with no draw-on effect.
- **Connector arrows:** curved paths in a full-player overlay, recomputed with `ResizeObserver`.
- **Controls:** Prev/Next, play/pause, speed (0.5×–3×), a timeline scrubber with tick marks for calls and
  exceptions, and keys `←/→` step, `Space` play, `Home/End`, `[`/`]` speed, `?` help. An ARIA live region
  reads the caption aloud.
- **Look:** system font stack, `ui-monospace` code, one accent color (indigo `#5E5CE6` light / `#7D7AFF` dark,
  used *only* for annotations and changes), generous whitespace, `prefers-color-scheme` with a manual override, WCAG AA contrast.

```html
<script type="module" src="visset-player.js"></script>
<visset-player src="bsearch.trace.json" theme="auto" speed="1"></visset-player>
<script>
  const p = document.querySelector('visset-player');
  p.addEventListener('stepchange', e => console.log(e.detail.index));
  p.goTo(5);   // also: p.trace = obj; p.play(); p.pause();
</script>
```

## 6. CLI and Python API

```bash
visset run bsearch.py                                  # trace the module, open in the browser
visset run bsearch.py --fn search --args "[1,3,5,7,9], 7"
visset run bsearch.py -o bsearch.html                  # export a standalone HTML file instead of opening it
visset trace bsearch.py -o bsearch.trace.json          # raw trace (for debugging tracers)
visset render bsearch.trace.json -o out.html
visset author walk.visset.yaml -o out.html             # M3
visset export bsearch.py --gif out.gif | --mp4 out.mp4 | --slides out/   # M6
visset structure app.py --cfg search | --calls | --classes               # M6
visset serve                                           # M7 playground
```

```python
import visset
t = visset.trace(open("bsearch.py").read(), entry="search", args=([1, 3, 5, 7, 9], 7))
visset.to_html(t, "bsearch.html")
# later: visset.show(t) in Jupyter
```

## 7. Authoring (M3) — preview

```yaml
visset: 0.1
title: Binary search, by hand
source: bsearch.py          # or inline:  code: |
steps:
  - circle: "lo, hi = 0, len(arr) - 1"
    caption: Start with the whole array as the search window.
    show: { arr: [1, 3, 5, 7, 9], lo: 0, hi: 4, pointers: { lo: arr, hi: arr } }
  - underline: "lo <= hi"
    caption: Keep going while the window is non-empty.
  - circle: { text: "arr[mid]", occurrence: 1 }
    caption: Compare the middle element with the target.
    link: arr[2]
```

There is also an **overlay mode**, `trace: auto`: trace the code automatically, and add captions and marks only
at chosen steps (`at: {line: 6, hit: 2}`), skipping noisy ones. AI mode (M8) is then just "an LLM writes this
overlay YAML", so the AI never touches the renderer, and you can review or edit what it produced.

## 8. Safety

Every trace runs in a **child process**: `python -I` (isolated mode), the script's own directory as working
directory (so `open("data.txt")` behaves like `python file.py`), `PYTHONHASHSEED=0` (reproducible traces), a scrubbed
environment, stdin closed unless given, `resource.setrlimit` for CPU seconds and address space, a wall-clock
timeout, and the step limit inside the tracer.
**Honest caveat:** this protects against *accidents* (infinite loops, memory blowups), not *malicious code*. The
code can still read your files or open sockets. That's fine for running your own snippets locally. The public
playground (M7) needs real isolation (a container with no network, read-only root, gVisor or nsjail).
On Windows there is no `setrlimit`, so only the timeout and step limit apply.

## 9. Tech choices and tradeoffs

| Choice | Chosen | Alternatives | Why |
|---|---|---|---|
| Python tracing | `sys.monitoring` + `ast` | settrace, debugpy/DAP | precise, fast, zero deps |
| Static parsing | tree-sitter (`visset[static]` extra) | per-language parsers | one API for many languages |
| Renderer | vanilla TS web component | React, Lit, Svelte | embeds anywhere, small |
| Hand-drawn marks | Rough.js (seeded) | rough-notation | sub-line ranges, stable |
| Heap layout | custom stable columns | ELK, dagre | animation stability |
| Graph layout | ELK.js (lazy) | dagre | better orthogonal CFGs |
| Video export | Playwright frame capture → Pillow GIF / ffmpeg MP4 (`visset[export]`) | in-browser MediaRecorder | deterministic frames, scriptable |
| Packaging | uv + hatchling; pnpm + esbuild | poetry; webpack | fast, simple |
| Schema checks | JSON Schema + shared golden fixtures | protobuf | human-readable, writable by hand |

## 10. Known limitations (up front)

- **Threads:** only the main thread is recorded. Events from other threads are ignored (and noted in `meta`).
- **async / generators:** frames that suspend and resume are shown, but event-loop internals are hidden. The
  "await" story is approximate.
- **Native code** (numpy, C extensions): opaque, shown as a box with the object's `repr`. There is no stepping into C.
- **Huge data:** containers are cut off at `maxItems` with a "… 950 more" marker, recursion at `maxDepth`,
  and traces at `maxSteps`.
- **Identity side effects:** the tracer keeps references to objects so their ids stay stable. That can delay
  `__del__` and weakref callbacks compared with an untraced run.
- **Compiled languages (DAP):** need a toolchain, debug symbols and an adapter installed. Values are strings,
  stop positions are often line-only, and heap identity is best effort.
- **The sandbox is not a security boundary** (see §8).

## 11. Milestones (each ends with a demo you can open)

| | Deliverable | Demo |
|---|---|---|
| M1 | schema v0.1, Python tracer, `visset run -o x.html`, player with code circles + variables + controls | binary search, step by step |
| M2 | heap boxes + reference arrows, call stack for recursion, code→diagram connectors, change pulses | recursive fib + list aliasing |
| M3 | YAML authoring (manual + overlay) + template captions | hand-written "two pointers" explainer |
| M4 | JS tracer + `npx visset` | the same binary search in JS, same player |
| M5 | linked list / tree / graph / 2D grid / recursion-tree renderers (auto-detect + hints) | reverse a linked list, BST insert |
| M6 | tree-sitter CFG / call graph / class diagram with code↔node hover; GIF/MP4/slides | CFG of bsearch; GIF of fib |
| M7 | `visset serve` playground (paste, run, share) | local web app |
| M8 | `visset explain` with Claude / OpenAI / Ollama providers → overlay YAML | AI-captioned walkthrough |

Each milestone is a branch and a pull request with tests: tracer unit tests, schema validation of every fixture and
example, and renderer tests (TS with Vitest, plus Playwright screenshot smoke tests from M2 on).
Since this runs in a cloud container, I'll also publish each milestone's demo HTML as a private link you can click through.
