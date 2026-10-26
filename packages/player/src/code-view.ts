import { type Box, drawMark } from './annotate';
import type { Mark, Source } from './types';

const SVG = 'http://www.w3.org/2000/svg';

interface Segment {
  node: Text;
  cpStart: number; // code point column where this text node starts
  text: string;
}

/**
 * Read-only code view. Each line is a row of token spans; an SVG overlay inside the scrolled
 * content holds the hand-drawn marks, so marks scroll with the code for free.
 */
export class CodeView {
  readonly el: HTMLElement;
  private readonly content: HTMLElement;
  private readonly svg: SVGSVGElement;
  private readonly rows: HTMLElement[] = [];
  private readonly segments: Segment[][] = [];
  private readonly lines: string[];
  private marks: Mark[] = [];
  private seed = 1;
  private activeRows: HTMLElement[] = [];
  private scrollTarget: number | undefined;
  private scrollTimer: number | undefined;

  constructor(source: Source) {
    this.lines = source.text.replace(/\n$/, '').split('\n');
    this.el = document.createElement('div');
    this.el.className = 'code-scroll';
    this.el.tabIndex = 0;
    this.el.setAttribute('role', 'region');
    this.el.setAttribute('aria-label', `Source code${source.path ? `: ${source.path}` : ''}`);
    this.content = document.createElement('div');
    this.content.className = 'code';
    this.svg = document.createElementNS(SVG, 'svg');
    this.svg.setAttribute('class', 'marks');
    this.svg.setAttribute('aria-hidden', 'true');
    this.renderLines(source);
    this.content.append(this.svg);
    this.el.append(this.content);
    new ResizeObserver(() => this.redraw(false)).observe(this.content);
  }

  private renderLines(source: Source): void {
    const byLine = new Map<number, [number, number, string][]>();
    for (const [line, col, end, kind] of source.tokens ?? []) {
      const list = byLine.get(line) ?? [];
      list.push([col, end, kind]);
      byLine.set(line, list);
    }
    const frag = document.createDocumentFragment();
    this.lines.forEach((text, idx) => {
      const lineNo = idx + 1;
      const row = document.createElement('div');
      row.className = 'line';
      const num = document.createElement('span');
      num.className = 'ln';
      num.textContent = String(lineNo);
      const src = document.createElement('span');
      src.className = 'src';
      const chars = Array.from(text); // index by code point, not UTF-16 unit
      const tokens = (byLine.get(lineNo) ?? []).sort((a, b) => a[0] - b[0]);
      const segs: Segment[] = [];
      let col = 0;
      const push = (from: number, to: number, kind?: string) => {
        if (to <= from) return;
        const value = chars.slice(from, to).join('');
        const node = document.createTextNode(value);
        if (kind) {
          const span = document.createElement('span');
          span.className = `tok-${kind}`;
          span.append(node);
          src.append(span);
        } else {
          src.append(node);
        }
        segs.push({ node, cpStart: from, text: value });
      };
      for (const [start, end, kind] of tokens) {
        if (start < col) continue;
        push(col, start);
        push(start, Math.min(end, chars.length), kind);
        col = Math.min(end, chars.length);
      }
      push(col, chars.length);
      if (!chars.length) src.append(document.createTextNode('​')); // keep empty lines tall
      row.append(num, src);
      frag.append(row);
      this.rows.push(row);
      this.segments.push(segs);
    });
    this.content.append(frag);
  }

  /** Show the marks for a step. `seed` keeps each step's hand-drawn wobble stable. */
  setFocus(marks: Mark[], seed: number, animate: boolean, callerLines: number[] = []): void {
    this.marks = marks;
    this.seed = seed;
    for (const row of this.activeRows) row.classList.remove('active', 'caller');
    this.activeRows = [];
    for (const line of callerLines) this.flag(line, 'caller');
    for (const m of marks) {
      for (let l = m.start[0]; l <= m.end[0]; l++) this.flag(l, 'active');
    }
    this.redraw(animate);
    this.reveal();
  }

  private flag(line: number, cls: string): void {
    const row = this.rows[line - 1];
    if (row) {
      row.classList.add(cls);
      this.activeRows.push(row);
    }
  }

  private redraw(animate: boolean): void {
    this.svg.replaceChildren();
    if (!this.content.isConnected) return;
    const gutter = (this.rows[0]?.querySelector<HTMLElement>('.src')?.offsetLeft ?? 40) - 12;
    this.marks.forEach((m, i) => {
      drawMark(this.svg, m.mark, this.boxes(m), {
        seed: this.seed * 31 + i + 1,
        animate,
        tone: m.tone ?? 'accent',
        gutter,
      });
    });
  }

  /** One box per covered line, in content coordinates. Leading indentation is skipped. */
  private boxes(m: Mark): Box[] {
    const origin = this.content.getBoundingClientRect();
    const out: Box[] = [];
    for (let line = m.start[0]; line <= m.end[0]; line++) {
      const text = this.lines[line - 1] ?? '';
      const len = Array.from(text).length;
      const indent = len - Array.from(text.trimStart()).length;
      const from = line === m.start[0] ? m.start[1] : indent;
      const to = line === m.end[0] ? m.end[1] : len;
      const rect = this.measure(line, from, Math.max(from, to));
      if (rect) {
        out.push({
          x: rect.left - origin.left,
          y: rect.top - origin.top,
          w: rect.width,
          h: rect.height,
        });
      }
    }
    return out;
  }

  private measure(line: number, from: number, to: number): DOMRect | null {
    const segs = this.segments[line - 1];
    const row = this.rows[line - 1];
    if (!segs || !row) return null;
    const src = row.querySelector('.src')!;
    if (!segs.length || from === to) {
      const r = src.getBoundingClientRect();
      return new DOMRect(r.left, r.top, Math.max(8, r.width), r.height);
    }
    const range = document.createRange();
    const locate = (col: number): [Text, number] => {
      for (const seg of segs) {
        const n = Array.from(seg.text).length;
        if (col <= seg.cpStart + n) {
          return [
            seg.node,
            Array.from(seg.text)
              .slice(0, col - seg.cpStart)
              .join('').length,
          ];
        }
      }
      const lastSeg = segs[segs.length - 1]!;
      return [lastSeg.node, lastSeg.text.length];
    };
    const [startNode, startOff] = locate(from);
    const [endNode, endOff] = locate(to);
    range.setStart(startNode, startOff);
    range.setEnd(endNode, endOff);
    const rect = range.getBoundingClientRect();
    const rowRect = row.getBoundingClientRect();
    // Use the row's height so marks sit evenly regardless of glyph metrics.
    return new DOMRect(rect.left, rowRect.top, rect.width, rowRect.height);
  }

  /**
   * Scroll the focused lines into view, centered, if they're not already visible.
   * Visibility is judged against where a smooth scroll is *heading*, not where it is now:
   * otherwise fast stepping sees the target "visible" mid-animation and never scrolls back.
   */
  private reveal(): void {
    const first = this.marks[0];
    if (!first) return;
    const row = this.rows[first.start[0] - 1];
    const lastRow = this.rows[first.end[0] - 1] ?? row;
    if (!row || !lastRow) return;
    const top = row.offsetTop;
    const bottom = lastRow.offsetTop + lastRow.offsetHeight;
    const height = this.el.clientHeight;
    const current = this.scrollTarget ?? this.el.scrollTop;
    const margin = 24;
    if (top >= current + margin && bottom <= current + height - margin) return;
    const max = this.el.scrollHeight - height;
    const target = Math.max(0, Math.min(max, top - (height - (bottom - top)) / 2));
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.scrollTarget = target;
    this.el.scrollTo({ top: target, behavior: reduce ? 'auto' : 'smooth' });
    clearTimeout(this.scrollTimer);
    this.scrollTimer = window.setTimeout(() => {
      this.scrollTarget = undefined;
    }, 600);
  }
}
