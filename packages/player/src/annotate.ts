import rough from 'roughjs';
import type { MarkKind } from './types';

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const SVG = 'http://www.w3.org/2000/svg';

export interface DrawOptions {
  seed: number; // same seed -> same wobble: revisiting a step shows the identical mark
  animate: boolean;
  tone: 'accent' | 'error';
  gutter: number; // x where brackets/arrows sit (left of the code)
}

/**
 * Draw one hand-drawn mark around `boxes` (one box per covered line) into `svg`.
 * Rough.js generates the sketchy paths; we animate them like a pen with stroke-dashoffset.
 */
export function drawMark(svg: SVGSVGElement, kind: MarkKind, boxes: Box[], opt: DrawOptions): void {
  if (!boxes.length) return;
  const rc = rough.svg(svg);
  const base = {
    seed: opt.seed,
    stroke: 'currentColor',
    strokeWidth: 1.7,
    roughness: 1.1,
    bowing: 1.2,
  };
  const g = document.createElementNS(SVG, 'g');
  g.setAttribute('class', `mark mark-${kind} tone-${opt.tone}`);
  const first = boxes[0]!;
  const last = boxes[boxes.length - 1]!;
  const left = Math.min(...boxes.map((b) => b.x));
  const right = Math.max(...boxes.map((b) => b.x + b.w));
  const top = first.y;
  const bottom = last.y + last.h;
  const multi = boxes.length > 1;
  const effective: MarkKind = multi && kind === 'circle' ? 'bracket' : kind;

  switch (effective) {
    case 'circle': {
      const padX = Math.min(14, 6 + first.w * 0.08);
      g.append(
        rc.ellipse(first.x + first.w / 2, first.y + first.h / 2, first.w + padX * 2, first.h + 12, {
          ...base,
          roughness: 0.9,
          curveStepCount: 14,
        }),
      );
      break;
    }
    case 'underline':
      for (const b of boxes) {
        const y = b.y + b.h - 1;
        g.append(rc.line(b.x - 1, y, b.x + b.w + 1, y + 0.5, { ...base, roughness: 0.8 }));
      }
      break;
    case 'strike':
      for (const b of boxes) {
        const y = b.y + b.h / 2;
        g.append(rc.line(b.x - 2, y, b.x + b.w + 2, y, base));
      }
      break;
    case 'box':
      g.append(rc.rectangle(left - 5, top - 2, right - left + 10, bottom - top + 4, base));
      break;
    case 'bracket': {
      const x = Math.max(2, opt.gutter);
      g.append(
        rc.linearPath(
          [
            [x + 7, top + 2],
            [x, top + 2],
            [x, bottom - 2],
            [x + 7, bottom - 2],
          ],
          { ...base, roughness: 0.7 },
        ),
      );
      if (kind === 'circle' || kind === 'bracket') {
        for (const b of boxes) g.prepend(highlight(b));
      }
      break;
    }
    case 'highlight':
      for (const b of boxes) g.append(highlight(b));
      break;
    case 'arrow': {
      const y = first.y + first.h / 2;
      const x2 = first.x - 6;
      const x1 = Math.max(2, x2 - 34);
      g.append(rc.line(x1, y, x2, y, base));
      g.append(
        rc.linearPath(
          [
            [x2 - 7, y - 5],
            [x2, y],
            [x2 - 7, y + 5],
          ],
          base,
        ),
      );
      break;
    }
  }
  svg.append(g);
  if (opt.animate) penIn(g);
}

function highlight(b: Box): SVGRectElement {
  const r = document.createElementNS(SVG, 'rect');
  r.setAttribute('x', String(b.x - 3));
  r.setAttribute('y', String(b.y + 1));
  r.setAttribute('width', String(b.w + 6));
  r.setAttribute('height', String(b.h - 2));
  r.setAttribute('rx', '4');
  r.setAttribute('class', 'mark-fill');
  return r;
}

/** Reveal each stroke like a pen drawing it; Rough's second pass follows the first. */
function penIn(g: SVGGElement): void {
  const paths = Array.from(g.querySelectorAll<SVGPathElement>('path'));
  const each = 320 / Math.max(1, Math.min(paths.length, 2));
  paths.forEach((path, i) => {
    const len = path.getTotalLength?.() ?? 0;
    if (!len) return;
    path.style.strokeDasharray = `${len} ${len}`;
    path.style.strokeDashoffset = String(len);
    path.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], {
      duration: each,
      delay: 40 + i * each * 0.55,
      easing: 'cubic-bezier(.3,.7,.4,1)',
      fill: 'forwards',
    });
  });
  for (const fill of g.querySelectorAll('.mark-fill')) {
    fill.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, fill: 'both' });
  }
}
