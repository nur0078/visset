# Contributing to visset

## Layout

```
schema/            trace.schema.json: the contract between tracers and the player
  fixtures/        golden traces, checked by both the Python and TypeScript tests
python/            the `visset` package: tracer, CLI, HTML export
packages/player/   <visset-player> web component (TypeScript)
examples/          programs the golden traces are made from
docs/              ARCHITECTURE.md and images
```

## Setup

Python 3.12+, Node 20+, [uv](https://docs.astral.sh/uv/) and pnpm.

```bash
pnpm install
pnpm build                 # player -> packages/player/dist and python/src/visset/_assets/player.js
cd python && uv sync
```

## Checks (CI runs exactly these)

```bash
# TypeScript (repo root)
pnpm check                 # Biome lint + format
pnpm typecheck
pnpm build && pnpm test    # unit tests + browser tests (Playwright Chromium)

# Python (python/)
uv run ruff check . && uv run ruff format --check .
uv run mypy                # strict
uv run pytest
```

`pnpm format` and `uv run ruff format .` fix formatting.

## Golden traces

`schema/fixtures/python-*.trace.json` are traced from `examples/*.py`. A test fails if the tracer's
output changes. If the change is intended, regenerate the fixtures and review the diff like code:

```bash
cd python && uv run python tests/update_goldens.py
```

## Changing the schema

The schema is the public contract. A change needs, in the same PR: the JSON Schema, the TypeScript
types (`packages/player/src/types.ts`), every tracer, and the regenerated fixtures. Breaking changes
bump the version in `"schema": "visset.trace/0.x"`.

## Pull requests

- One topic per branch and PR. Milestones land as separate PRs.
- Commit messages: `area: what changed` (e.g. `tracer: split statements sharing a line`).
- Add tests for behavior changes. For tracer changes, prefer an assertion on the exact focused
  text (`focused(trace)`) or caption, and say what a learner would see.
- Be honest about limitations in docs: if something isn't handled, write it down.
