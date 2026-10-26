import { CodeView } from './code-view';
import { parseCaption, TraceModel } from './model';
import { StateView } from './state-view';
import { css } from './styles';
import type { Trace } from './types';

const SPEEDS = [0.5, 1, 1.5, 2, 3];
const BASE_INTERVAL_MS = 1300;

const ICON = {
  prev: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10.3 2.3a1 1 0 0 1 0 1.4L6 8l4.3 4.3a1 1 0 1 1-1.4 1.4l-5-5a1 1 0 0 1 0-1.4l5-5a1 1 0 0 1 1.4 0Z"/></svg>',
  next: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.7 2.3a1 1 0 0 0 0 1.4L10 8l-4.3 4.3a1 1 0 1 0 1.4 1.4l5-5a1 1 0 0 0 0-1.4l-5-5a1 1 0 0 0-1.4 0Z"/></svg>',
  play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 2.9v10.2a.9.9 0 0 0 1.4.76l7.6-5.1a.9.9 0 0 0 0-1.5L6.4 2.1A.9.9 0 0 0 5 2.9Z"/></svg>',
  pause:
    '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3.2" height="11" rx="1"/><rect x="9.3" y="2.5" width="3.2" height="11" rx="1"/></svg>',
};

const TEMPLATE = `
<div class="player" part="player">
  <header class="bar"><span class="title"></span><span class="meta"></span></header>
  <div class="panes">
    <section class="pane code-pane" aria-label="Code"><div class="pane-head file"></div></section>
    <section class="pane state-pane" aria-label="Program state"></section>
  </div>
  <div class="caption-row">
    <p class="caption" aria-live="polite"></p>
    <p class="notice" hidden></p>
  </div>
  <nav class="controls" aria-label="Walkthrough controls">
    <button class="btn prev" type="button" aria-label="Previous step (Left arrow)" title="Previous (←)">${ICON.prev}</button>
    <button class="btn play" type="button" aria-label="Play (Space)" title="Play (Space)">${ICON.play}</button>
    <button class="btn next" type="button" aria-label="Next step (Right arrow)" title="Next (→)">${ICON.next}</button>
    <input class="slider" type="range" min="0" max="0" value="0" step="1" aria-label="Step">
    <span class="counter" aria-hidden="true"></span>
    <select class="speed" aria-label="Playback speed" title="Speed ([ and ])">
      ${SPEEDS.map((s) => `<option value="${s}"${s === 1 ? ' selected' : ''}>${s}×</option>`).join('')}
    </select>
  </nav>
</div>`;

/**
 * `<visset-player>`: plays a visset trace as a guided, step-by-step explainer.
 *
 * Load a trace with the `src` attribute (URL), a child `<script type="application/json">`,
 * or the `trace` property. Attributes: `theme="auto|light|dark"`, `speed`, `step`,
 * `global-keys` (keyboard shortcuts work anywhere on the page, not only when focused).
 * Fires `stepchange` with `{ index, step }`.
 */
export class VissetPlayer extends HTMLElement {
  static observedAttributes = ['src', 'step', 'speed'];

  private model: TraceModel | null = null;
  private idx = 0;
  private timer: number | undefined;
  private speed = 1;
  private codeView: CodeView | null = null;
  private stateView = new StateView();
  private root: ShadowRoot;
  private els!: {
    title: HTMLElement;
    meta: HTMLElement;
    file: HTMLElement;
    codePane: HTMLElement;
    caption: HTMLElement;
    notice: HTMLElement;
    prev: HTMLButtonElement;
    next: HTMLButtonElement;
    play: HTMLButtonElement;
    slider: HTMLInputElement;
    counter: HTMLElement;
    speed: HTMLSelectElement;
  };
  private onWindowKey = (e: KeyboardEvent) => this.handleKey(e);

  constructor() {
    super();
    this.root = this.attachShadow({ mode: 'open' });
    this.root.innerHTML = `<style>${css}</style>${TEMPLATE}`;
    const q = <T extends Element>(sel: string) => this.root.querySelector<T>(sel)!;
    this.els = {
      title: q('.title'),
      meta: q('.meta'),
      file: q('.file'),
      codePane: q('.code-pane'),
      caption: q('.caption'),
      notice: q('.notice'),
      prev: q('.prev'),
      next: q('.next'),
      play: q('.play'),
      slider: q('.slider'),
      counter: q('.counter'),
      speed: q('.speed'),
    };
    q('.state-pane').append(this.stateView.el);
    this.els.prev.addEventListener('click', () => this.prev());
    this.els.next.addEventListener('click', () => this.next());
    this.els.play.addEventListener('click', () => this.toggle());
    this.els.slider.addEventListener('input', () => {
      this.pause();
      this.goTo(Number(this.els.slider.value));
    });
    this.els.speed.addEventListener('change', () => this.setSpeed(Number(this.els.speed.value)));
    this.addEventListener('keydown', (e) => {
      if (!this.hasAttribute('global-keys')) this.handleKey(e);
    });
  }

  connectedCallback(): void {
    if (!this.hasAttribute('tabindex')) this.tabIndex = 0;
    if (this.hasAttribute('global-keys')) window.addEventListener('keydown', this.onWindowKey);
    if (!this.model) {
      const inline = this.querySelector('script[type="application/json"]');
      if (inline?.textContent) this.trace = JSON.parse(inline.textContent) as Trace;
      else if (this.getAttribute('src')) void this.load(this.getAttribute('src')!);
    }
  }

  disconnectedCallback(): void {
    this.pause();
    window.removeEventListener('keydown', this.onWindowKey);
  }

  attributeChangedCallback(name: string, old: string | null, value: string | null): void {
    if (old === value) return;
    if (name === 'src' && value && this.isConnected) void this.load(value);
    if (name === 'step' && value !== null) this.goTo(Number(value));
    if (name === 'speed' && value !== null) this.setSpeed(Number(value));
  }

  // ------------------------------------------------------------------ public API

  get trace(): Trace | null {
    return this.model?.trace ?? null;
  }

  set trace(trace: Trace | null) {
    this.pause();
    if (!trace) return;
    try {
      this.model = new TraceModel(trace);
    } catch (err) {
      this.showError(String(err instanceof Error ? err.message : err));
      return;
    }
    this.mount();
  }

  get index(): number {
    return this.idx;
  }

  get length(): number {
    return this.model?.length ?? 0;
  }

  goTo(i: number, animate = true): void {
    const m = this.model;
    if (!m?.length || Number.isNaN(i)) return;
    const next = Math.max(0, Math.min(m.length - 1, Math.trunc(i)));
    const moved = next !== this.idx;
    this.idx = next;
    this.render(animate && moved && !reducedMotion());
    if (moved) {
      this.dispatchEvent(
        new CustomEvent('stepchange', { detail: { index: next, step: m.step(next) } }),
      );
    }
  }

  next(): void {
    this.goTo(this.idx + 1);
  }

  prev(): void {
    this.pause();
    this.goTo(this.idx - 1);
  }

  play(): void {
    if (!this.model || this.timer !== undefined) return;
    if (this.idx >= this.model.length - 1) this.goTo(0);
    this.timer = window.setInterval(() => {
      if (!this.model || this.idx >= this.model.length - 1) this.pause();
      else this.next();
    }, BASE_INTERVAL_MS / this.speed);
    this.syncPlayButton();
  }

  pause(): void {
    if (this.timer !== undefined) window.clearInterval(this.timer);
    this.timer = undefined;
    this.syncPlayButton();
  }

  toggle(): void {
    if (this.timer === undefined) this.play();
    else this.pause();
  }

  setSpeed(speed: number): void {
    if (!Number.isFinite(speed) || speed <= 0) return;
    this.speed = speed;
    const option = SPEEDS.includes(speed) ? String(speed) : '';
    if (option) this.els.speed.value = option;
    if (this.timer !== undefined) {
      this.pause();
      this.play();
    }
  }

  // ------------------------------------------------------------------ internals

  private async load(url: string): Promise<void> {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.trace = (await res.json()) as Trace;
    } catch (err) {
      this.showError(`Could not load ${url}: ${err instanceof Error ? err.message : err}`);
    }
  }

  private mount(): void {
    const m = this.model!;
    const { meta, sources } = m.trace;
    const source = sources[0]!;
    this.els.title.textContent = meta.title ?? source.path ?? 'Walkthrough';
    const lang = meta.language ? meta.language[0]!.toUpperCase() + meta.language.slice(1) : '';
    this.els.meta.textContent = [
      lang,
      `${m.length.toLocaleString()} step${m.length === 1 ? '' : 's'}`,
    ]
      .filter(Boolean)
      .join(' · ');
    const title = this.els.title.textContent;
    this.els.file.textContent = source.path && source.path !== title ? source.path : 'Code';
    this.codeView?.el.remove();
    this.codeView = new CodeView(source);
    this.els.codePane.append(this.codeView.el);
    this.els.slider.max = String(Math.max(0, m.length - 1));
    this.idx = Math.max(0, Math.min(m.length - 1, Number(this.getAttribute('step') ?? 0) || 0));
    const speed = Number(this.getAttribute('speed'));
    if (speed > 0) this.setSpeed(speed);
    // Wait a frame so fonts and layout settle before measuring where to draw marks.
    requestAnimationFrame(() => this.render(false));
  }

  private render(animate: boolean): void {
    const m = this.model;
    if (!m?.length) {
      this.els.caption.textContent = 'This trace has no steps.';
      return;
    }
    const i = this.idx;
    const step = m.step(i);
    const callers = step.stack
      .slice(0, -1)
      .map((f) => f.line ?? 0)
      .filter((l) => l > 0);
    this.codeView?.setFocus(step.focus, i + 1, animate, callers);
    this.stateView.render(m, i, animate);

    const cap = this.els.caption;
    cap.replaceChildren(
      ...parseCaption(step.caption ?? '').map((part) => {
        if (!part.code) return document.createTextNode(part.text);
        const code = document.createElement('code');
        code.textContent = part.text;
        return code;
      }),
    );
    cap.classList.toggle('error', step.kind === 'exception');
    if (animate) {
      cap.classList.remove('enter');
      void cap.offsetWidth;
      cap.classList.add('enter');
    }
    this.renderNotice(i === m.length - 1);

    const n = m.length;
    this.els.slider.value = String(i);
    this.els.slider.style.setProperty('--pct', n > 1 ? `${(i / (n - 1)) * 100}%` : '100%');
    this.els.slider.setAttribute('aria-valuetext', `Step ${i + 1} of ${n}: ${step.caption ?? ''}`);
    this.els.counter.textContent = `${(i + 1).toLocaleString()} / ${n.toLocaleString()}`;
    this.els.prev.disabled = i === 0;
    this.els.next.disabled = i === n - 1;
  }

  private renderNotice(atEnd: boolean): void {
    const { truncated, error } = this.model!.trace.meta;
    const notice = this.els.notice;
    let text = '';
    if (atEnd && error) {
      const where = error.line ? ` on line ${error.line}` : '';
      text = `The program stopped with ${error.type}${where}: ${error.message}`;
    } else if (atEnd && truncated) {
      const limit = truncated.limit ?? 0;
      text =
        truncated.reason === 'maxSteps'
          ? `Stopped after ${limit.toLocaleString()} steps: the program may loop forever.`
          : truncated.reason === 'timeout'
            ? `Stopped after ${limit / 1000}s: the program took too long.`
            : truncated.reason === 'maxStack'
              ? `Stopped at ${limit} nested calls: the recursion may never end.`
              : 'Stopped early.';
    }
    notice.textContent = text;
    notice.hidden = !text;
    notice.classList.toggle('error', Boolean(atEnd && error));
  }

  private showError(message: string): void {
    this.els.caption.textContent = message;
    this.els.caption.classList.add('error');
  }

  private syncPlayButton(): void {
    const playing = this.timer !== undefined;
    this.els.play.innerHTML = playing ? ICON.pause : ICON.play;
    this.els.play.setAttribute('aria-label', playing ? 'Pause (Space)' : 'Play (Space)');
    this.els.play.title = playing ? 'Pause (Space)' : 'Play (Space)';
  }

  private handleKey(e: KeyboardEvent): void {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const target = e.composedPath()[0];
    if (
      target instanceof HTMLElement &&
      target.closest('input:not(.slider), select, textarea, [contenteditable]')
    ) {
      return;
    }
    const m = this.model;
    if (!m) return;
    const actions: Record<string, () => void> = {
      ArrowRight: () => {
        this.pause();
        this.next();
      },
      ArrowLeft: () => this.prev(),
      ' ': () => this.toggle(),
      Home: () => {
        this.pause();
        this.goTo(0);
      },
      End: () => {
        this.pause();
        this.goTo(m.length - 1);
      },
      '[': () => this.setSpeed(SPEEDS[Math.max(0, SPEEDS.indexOf(this.speed) - 1)] ?? 1),
      ']': () =>
        this.setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(this.speed) + 1)] ?? 1),
    };
    const action = actions[e.key];
    if (action) {
      e.preventDefault();
      action();
    }
  }
}

function reducedMotion(): boolean {
  return matchMedia('(prefers-reduced-motion: reduce)').matches;
}
