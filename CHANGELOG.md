# Changelog

## Unreleased

- Notebooks: `visset.show(...)` plays the walkthrough under the cell in Jupyter, JupyterLab,
  VS Code and Colab instead of returning a temp file path, and `to_html(...)` displays as the
  player instead of a wall of HTML text.

## 0.1.0

First release.

- Python tracer (3.12+, `sys.monitoring`): every step records the exact expression that ran
  (column-precise), the call stack, variables and output.
- Visualize one function (`--fn`, `visset.show(fn, *args)`), part of a function (`--lines`),
  or a snippet with inputs (`--given`).
- Plain-English captions from templates.
- `<visset-player>` web component: hand-drawn marks, synced state panel, play/pause, speed,
  timeline, keyboard shortcuts, light and dark themes, reduced motion.
- Standalone HTML export that works offline.
- Sandboxed runs with step, time, memory and recursion limits.
