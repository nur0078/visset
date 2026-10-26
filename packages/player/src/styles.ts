// One accent color (indigo), used only for the things that matter at this step:
// the hand-drawn marks, changed values, and the primary control. Syntax colors stay muted
// so they never compete with the annotation.
export const css = /* css */ `
:host {
  --font-ui: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Segoe UI", Roboto, system-ui, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Code", Menlo, Consolas, monospace;
  --accent: #5e5ce6;
  --accent-soft: rgba(94, 92, 230, 0.11);
  --accent-strong: rgba(94, 92, 230, 0.28);
  --on-accent: #fff;
  --error: #d70015;
  --error-soft: rgba(215, 0, 21, 0.09);
  --surface: #ffffff;
  --panel: #fbfbfd;
  --frame: #ffffff;
  --text: #1d1d1f;
  --muted: #6e6e73;
  --faint: #a1a1a6;
  --line: rgba(0, 0, 0, 0.08);
  --active-line: rgba(94, 92, 230, 0.06);
  --caller-line: rgba(0, 0, 0, 0.03);
  --code-bg: rgba(0, 0, 0, 0.05);
  --track: rgba(0, 0, 0, 0.1);
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 12px 40px rgba(0, 0, 0, 0.07);
  --syn-keyword: #9b2393;
  --syn-string: #1d7a4f;
  --syn-number: #8a5100;
  --syn-comment: #6e6e73;
  --syn-builtin: #2c5d8f;
  --syn-def: #1d1d1f;
  display: block;
  height: 600px;
  min-height: 420px;
  container-type: inline-size;
  color-scheme: light;
  -webkit-font-smoothing: antialiased;
}
:host([hidden]) { display: none; }
${darkTokens(':host([theme="dark"])')}
@media (prefers-color-scheme: dark) {
  ${darkTokens(':host(:not([theme="light"]))')}
}

* { box-sizing: border-box; }
.player {
  height: 100%;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  background: var(--surface);
  color: var(--text);
  font: 14px/1.45 var(--font-ui);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow);
  overflow: hidden;
}
.player:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* header */
.bar { display: flex; align-items: baseline; gap: 12px; padding: 16px 22px 12px; min-width: 0; }
.title { font-weight: 600; font-size: 15px; letter-spacing: -0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta { margin-left: auto; font-size: 12px; color: var(--muted); white-space: nowrap; }

/* panes */
.panes { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 12px; padding: 0 14px; min-height: 0; }
.pane { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.pane-head { flex: none; font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); padding: 11px 14px 5px; }

/* code */
.code-scroll { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
.code-scroll:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 0 0 12px 12px; }
.code { position: relative; min-width: max-content; padding: 4px 0 28px; font: 13.5px/1.8 var(--font-mono); font-variant-ligatures: none; }
.line { display: flex; padding-right: 32px; transition: background-color 0.25s ease; }
.ln { flex: none; width: 3.4em; padding-right: 1.3em; text-align: right; color: var(--faint); user-select: none; }
.src { white-space: pre; }
.line.caller { background: var(--caller-line); }
.line.active { background: var(--active-line); }
.line.active .ln { color: var(--text); }
.marks { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; pointer-events: none; color: var(--accent); }
.marks .tone-error { color: var(--error); }
.mark-fill { fill: var(--accent-soft); stroke: none; }
.tone-error .mark-fill { fill: var(--error-soft); }
.tok-keyword { color: var(--syn-keyword); }
.tok-constant { color: var(--syn-keyword); }
.tok-string { color: var(--syn-string); }
.tok-number { color: var(--syn-number); }
.tok-comment { color: var(--syn-comment); font-style: italic; }
.tok-builtin { color: var(--syn-builtin); }
.tok-definition { color: var(--syn-def); font-weight: 600; }

/* state */
.state { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.frames { position: relative; flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain; display: flex; flex-direction: column; gap: 8px; padding: 2px 12px 12px; }
.frame { flex: none; background: var(--frame); border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px 9px; transition: border-color 0.25s ease, box-shadow 0.25s ease; }
.frame.top { border-color: var(--accent-strong); box-shadow: inset 3px 0 0 var(--accent); }
.frame.entering { animation: vs-enter 0.32s cubic-bezier(.2,.8,.3,1); }
.frame-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 4px; font-size: 12.5px; }
.frame-name { font-weight: 600; font-family: var(--font-mono); }
.frame-ret { margin-left: auto; font: 12px var(--font-mono); color: var(--accent); }
.vars { display: grid; grid-template-columns: max-content minmax(0, 1fr); column-gap: 16px; row-gap: 2px; font: 13px/1.6 var(--font-mono); }
.var-name { color: var(--muted); }
.var-value { min-width: 0; overflow-wrap: anywhere; border-radius: 5px; margin: 0 -5px; padding: 0 5px; transition: background-color 0.4s ease; }
.var-value[data-type="str"] { color: var(--syn-string); }
.var-value.changed { background: var(--accent-soft); }
.var-value.pulse { animation: vs-pulse 0.9s ease-out; }
.empty { color: var(--faint); font: 12.5px var(--font-ui); }
.console { flex: 0 0 auto; max-height: 36%; display: flex; flex-direction: column; border-top: 1px solid var(--line); }
.console pre { margin: 0; padding: 0 14px 12px; min-height: 2.4em; overflow: auto; font: 12.5px/1.6 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.console mark.fresh { background: var(--accent-soft); color: inherit; border-radius: 3px; }

/* caption */
.caption-row { padding: 16px 22px 4px; min-height: 0; }
.caption { margin: 0; min-height: 2.9em; font-size: 15.5px; line-height: 1.45; letter-spacing: -0.005em; text-wrap: pretty; }
.caption.enter { animation: vs-fade 0.22s ease-out; }
.caption code { font: 0.88em var(--font-mono); background: var(--code-bg); padding: 1px 5px; border-radius: 5px; }
.caption.error code { color: var(--error); background: var(--error-soft); }
.notice { margin: 8px 0 0; padding: 7px 11px; font-size: 12.5px; color: var(--muted); background: var(--code-bg); border-radius: 8px; }
.notice.error { color: var(--error); background: var(--error-soft); }

/* controls */
.controls { display: flex; align-items: center; gap: 6px; padding: 8px 16px 16px; }
button, select { font: inherit; color: inherit; }
.btn { display: inline-grid; place-items: center; width: 34px; height: 34px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: var(--text); cursor: pointer; transition: background-color 0.15s ease, transform 0.1s ease; }
.btn:hover { background: var(--code-bg); }
.btn:active { transform: scale(0.94); }
.btn:disabled { color: var(--faint); cursor: default; background: transparent; transform: none; }
.btn svg { width: 16px; height: 16px; fill: currentColor; }
.btn.play { width: 40px; height: 40px; background: var(--accent); color: var(--on-accent); }
.btn.play:hover { filter: brightness(1.08); background: var(--accent); }
.btn:focus-visible, .speed:focus-visible, .slider:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.slider { flex: 1; min-width: 60px; margin: 0 8px; height: 22px; background: transparent; appearance: none; -webkit-appearance: none; cursor: pointer; --pct: 0%; }
.slider::-webkit-slider-runnable-track { height: 4px; border-radius: 2px; background: linear-gradient(to right, var(--accent) var(--pct), var(--track) var(--pct)); }
.slider::-moz-range-track { height: 4px; border-radius: 2px; background: linear-gradient(to right, var(--accent) var(--pct), var(--track) var(--pct)); }
.slider::-webkit-slider-thumb { -webkit-appearance: none; width: 16px; height: 16px; margin-top: -6px; border-radius: 50%; background: #fff; border: 0; box-shadow: 0 0 0 0.5px rgba(0,0,0,0.12), 0 1px 4px rgba(0,0,0,0.25); }
.slider::-moz-range-thumb { width: 16px; height: 16px; border-radius: 50%; background: #fff; border: 0; box-shadow: 0 0 0 0.5px rgba(0,0,0,0.12), 0 1px 4px rgba(0,0,0,0.25); }
.counter { min-width: 6.5em; text-align: right; font-size: 12.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
.speed { height: 28px; padding: 0 6px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); font-size: 12.5px; color: var(--muted); cursor: pointer; }

.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

@container (max-width: 720px) {
  .panes { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1.25fr) minmax(0, 1fr); }
  .bar { padding: 14px 16px 10px; }
  .caption-row { padding: 12px 16px 2px; }
  .caption { font-size: 15px; }
  .controls { padding: 6px 10px 12px; }
  .counter { min-width: 0; }
  .speed { display: none; }
}

@keyframes vs-pulse { 0% { background: var(--accent-strong); } 100% { background: var(--accent-soft); } }
@keyframes vs-enter { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
@keyframes vs-fade { from { opacity: 0.2; transform: translateY(2px); } to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
`;

function darkTokens(selector: string): string {
  return `${selector} {
    --accent: #8b88ff;
    --accent-soft: rgba(139, 136, 255, 0.16);
    --accent-strong: rgba(139, 136, 255, 0.36);
    --on-accent: #0b0b14;
    --error: #ff6961;
    --error-soft: rgba(255, 105, 97, 0.14);
    --surface: #161618;
    --panel: #1c1c1e;
    --frame: #232326;
    --text: #f5f5f7;
    --muted: #a1a1a6;
    --faint: #6e6e73;
    --line: rgba(255, 255, 255, 0.09);
    --active-line: rgba(139, 136, 255, 0.1);
    --caller-line: rgba(255, 255, 255, 0.035);
    --code-bg: rgba(255, 255, 255, 0.08);
    --track: rgba(255, 255, 255, 0.16);
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.3), 0 12px 40px rgba(0, 0, 0, 0.4);
    --syn-keyword: #ff7ab2;
    --syn-string: #7ed4a0;
    --syn-number: #e5b567;
    --syn-comment: #8e8e93;
    --syn-builtin: #7cc0f5;
    --syn-def: #f5f5f7;
    color-scheme: dark;
  }`;
}
