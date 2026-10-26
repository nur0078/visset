import type { TraceModel } from './model';
import type { Frame, Value } from './types';

/**
 * Call stack frames with their variables, plus the program's output.
 * DOM nodes are keyed by frame id and variable name and reused between steps, so a changed
 * value can pulse in place instead of the whole panel being rebuilt.
 */
export class StateView {
  readonly el: HTMLElement;
  private readonly framesEl: HTMLElement;
  private readonly outputEl: HTMLPreElement;
  private readonly frameEls = new Map<string, HTMLElement>();

  constructor() {
    this.el = document.createElement('div');
    this.el.className = 'state';
    const head = document.createElement('div');
    head.className = 'pane-head';
    head.textContent = 'Frames';
    this.framesEl = document.createElement('div');
    this.framesEl.className = 'frames';
    this.framesEl.setAttribute('role', 'list');
    this.framesEl.setAttribute('aria-label', 'Call stack');
    const console = document.createElement('div');
    console.className = 'console';
    const consoleHead = document.createElement('div');
    consoleHead.className = 'pane-head';
    consoleHead.textContent = 'Output';
    this.outputEl = document.createElement('pre');
    this.outputEl.setAttribute('aria-label', 'Program output');
    console.append(consoleHead, this.outputEl);
    this.el.append(head, this.framesEl, console);
  }

  render(model: TraceModel, i: number, animate: boolean): void {
    const step = model.step(i);
    const changes = model.changes(i);
    const live = new Set<string>();
    step.stack.forEach((frame, idx) => {
      live.add(frame.id);
      const el = this.frameEl(frame, changes.has(frame.id) && animate);
      el.classList.toggle('top', idx === step.stack.length - 1);
      this.fillFrame(el, frame, model, i, changes, animate);
      // Keep DOM order equal to stack order (outermost first).
      if (this.framesEl.children[idx] !== el)
        this.framesEl.insertBefore(el, this.framesEl.children[idx] ?? null);
    });
    for (const [id, el] of this.frameEls) {
      if (!live.has(id)) {
        el.remove();
        this.frameEls.delete(id);
      }
    }
    if (!step.stack.length) {
      this.framesEl.innerHTML = '<p class="empty">No frames: the program has not started.</p>';
      this.frameEls.clear();
    } else {
      this.framesEl.querySelector(':scope > .empty')?.remove();
    }
    // Keep the newest frame visible. (Not scrollIntoView: that would also scroll the host page.)
    const top = this.framesEl.lastElementChild as HTMLElement | null;
    if (
      top &&
      top.offsetTop + top.offsetHeight > this.framesEl.scrollTop + this.framesEl.clientHeight
    ) {
      this.framesEl.scrollTop = top.offsetTop + top.offsetHeight - this.framesEl.clientHeight;
    }
    this.renderOutput(model, i);
  }

  private frameEl(frame: Frame, entering: boolean): HTMLElement {
    let el = this.frameEls.get(frame.id);
    if (!el) {
      el = document.createElement('section');
      el.className = 'frame';
      el.setAttribute('role', 'listitem');
      el.innerHTML =
        '<header class="frame-head"><span class="frame-name"></span><span class="frame-ret"></span></header><div class="vars"></div>';
      if (entering) el.classList.add('entering');
      this.frameEls.set(frame.id, el);
    }
    return el;
  }

  private fillFrame(
    el: HTMLElement,
    frame: Frame,
    model: TraceModel,
    i: number,
    changes: Set<string>,
    animate: boolean,
  ): void {
    el.querySelector('.frame-name')!.textContent = frame.name;
    el.setAttribute('aria-label', `Frame ${frame.name}`);
    const ret = el.querySelector<HTMLElement>('.frame-ret')!;
    const back = frame.returnValue ?? frame.yieldValue;
    ret.textContent = back
      ? `${frame.returnValue ? 'returns' : 'yields'} ${model.format(i, back, 40)}`
      : '';
    ret.classList.toggle('changed', Boolean(back));

    const vars = el.querySelector<HTMLElement>('.vars')!;
    if (!frame.locals.length) {
      vars.innerHTML = '<span class="empty">no variables yet</span>';
      return;
    }
    vars.querySelector(':scope > .empty')?.remove();
    const existing = new Map<string, [HTMLElement, HTMLElement]>();
    for (const nameEl of vars.querySelectorAll<HTMLElement>('.var-name')) {
      existing.set(nameEl.dataset.name!, [nameEl, nameEl.nextElementSibling as HTMLElement]);
    }
    const keep = new Set<string>();
    let cursor: Element | null = vars.firstElementChild;
    for (const [name, value] of frame.locals) {
      keep.add(name);
      let pair = existing.get(name);
      if (!pair) {
        const n = document.createElement('span');
        n.className = 'var-name';
        n.dataset.name = name;
        n.textContent = name;
        const v = document.createElement('span');
        v.className = 'var-value';
        pair = [n, v];
      }
      const [n, v] = pair;
      if (cursor !== n) vars.insertBefore(n, cursor);
      vars.insertBefore(v, n.nextSibling);
      cursor = v.nextElementSibling;
      this.setValue(v, value, model, i, changes.has(`${frame.id}.${name}`), animate);
    }
    for (const [name, [n, v]] of existing) {
      if (!keep.has(name)) {
        n.remove();
        v.remove();
      }
    }
  }

  private setValue(
    el: HTMLElement,
    value: Value,
    model: TraceModel,
    i: number,
    changed: boolean,
    animate: boolean,
  ): void {
    el.textContent = model.format(i, value);
    el.dataset.type = 'p' in value ? value.t : (model.resolve(i, value)?.shape ?? 'ref');
    el.title = 'p' in value ? value.t : (model.resolve(i, value)?.type ?? '');
    el.classList.remove('changed', 'pulse');
    if (changed) {
      el.classList.add('changed');
      if (animate) {
        void el.offsetWidth; // restart the CSS animation
        el.classList.add('pulse');
      }
    }
  }

  private renderOutput(model: TraceModel, i: number): void {
    const { text, freshFrom } = model.output(i);
    this.outputEl.replaceChildren();
    if (!text) {
      const empty = document.createElement('span');
      empty.className = 'empty';
      empty.textContent = 'Nothing printed yet.';
      this.outputEl.append(empty);
      return;
    }
    this.outputEl.append(document.createTextNode(text.slice(0, freshFrom)));
    if (freshFrom < text.length) {
      const fresh = document.createElement('mark');
      fresh.className = 'fresh';
      fresh.textContent = text.slice(freshFrom);
      this.outputEl.append(fresh);
    }
    this.outputEl.scrollTop = this.outputEl.scrollHeight;
  }
}
