import { type GraphEdge, LAYOUT, type NodeBox, type ObjectGraph } from './graph';

const SVG = 'http://www.w3.org/2000/svg';

function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  return el;
}

/**
 * Draws an ObjectGraph: boxes for objects, arrows for references, and the innermost frame's
 * variable names above the objects they name. Node elements are keyed by object id and reused,
 * so a field that changed pulses in place and nothing moves between steps.
 */
export class GraphView {
  readonly el: HTMLElement;
  private readonly svgEl: SVGSVGElement;
  private readonly edgeLayer: SVGGElement;
  private readonly nodeLayer: SVGGElement;
  private readonly nodeEls = new Map<string, SVGGElement>();

  constructor(private readonly graph: ObjectGraph) {
    this.el = document.createElement('div');
    this.el.className = 'graph';
    const head = document.createElement('div');
    head.className = 'pane-head';
    head.textContent = 'Objects';
    const box = document.createElement('div');
    box.className = 'graph-box';
    this.svgEl = svg('svg', {
      class: 'graph-svg',
      viewBox: `0 0 ${graph.width} ${graph.height}`,
      role: 'img',
    });
    const defs = svg('defs');
    const marker = svg('marker', {
      id: 'vs-arrow',
      viewBox: '0 0 10 10',
      refX: 9,
      refY: 5,
      markerWidth: 7,
      markerHeight: 7,
      orient: 'auto-start-reverse',
    });
    marker.append(svg('path', { d: 'M1 1.5 9 5 1 8.5', class: 'arrow-head' }));
    defs.append(marker);
    this.edgeLayer = svg('g', { class: 'edges' });
    this.nodeLayer = svg('g', { class: 'nodes' });
    this.svgEl.append(defs, this.edgeLayer, this.nodeLayer);
    box.append(this.svgEl);
    this.el.append(head, box);
    new ResizeObserver(() => this.fit(box)).observe(box);
  }

  render(i: number, animate: boolean): void {
    const { nodes, edges } = this.graph.at(i);
    // Compare with the step before (not the last one drawn), as the Frames pane does.
    const prev = new Map(
      (i > 0 ? this.graph.at(i - 1).nodes : []).map((n) => [
        n.id,
        new Map(n.rows.map(([name, , full]) => [name, full])),
      ]),
    );
    const live = new Set(nodes.map((n) => n.id));
    for (const node of nodes) {
      const box = this.graph.boxes.get(node.id)!;
      let g = this.nodeEls.get(node.id);
      const entering = !g;
      if (!g) {
        g = this.createNode(box);
        this.nodeEls.set(node.id, g);
      }
      if (entering && animate) g.classList.add('entering');
      else g.classList.remove('entering');
      this.nodeLayer.append(g);

      const title = g.querySelector<SVGTextElement>('.node-title')!;
      title.textContent = node.title || node.type;
      title.classList.toggle('typename', !node.title);
      g.querySelector('title')!.textContent = node.title
        ? `${node.title} (${node.type})`
        : node.type;

      const tag = g.querySelector<SVGTextElement>('.node-tag')!;
      // `x = Value(2.0, label='x')` would say x twice.
      tag.textContent = node.names.filter((n) => n !== node.title).join(', ');

      const rowsEl = g.querySelector<SVGGElement>('.node-rows')!;
      const before = prev.get(node.id);
      rowsEl.replaceChildren(
        ...node.rows.map(([name, display, full], n) => {
          const y = LAYOUT.headH + n * LAYOUT.rowH + 13;
          const row = svg('g', { class: 'node-row' });
          const changed = before !== undefined && before.get(name) !== full;
          if (changed) {
            row.classList.add('changed');
            if (animate) row.classList.add('pulse');
            row.append(
              svg('rect', {
                class: 'row-hl',
                x: 3,
                y: y - 13,
                width: box.w - 6,
                height: LAYOUT.rowH,
                rx: 4,
              }),
            );
          }
          const k = svg('text', { class: 'row-name', x: LAYOUT.padX, y });
          k.textContent = name;
          const v = svg('text', { class: 'row-value', x: box.w - LAYOUT.padX, y });
          v.textContent = display;
          if (display !== full) v.append(Object.assign(svg('title'), { textContent: full }));
          row.append(k, v);
          return row;
        }),
      );
    }
    for (const [id, g] of this.nodeEls) {
      if (!live.has(id)) {
        g.remove();
        this.nodeEls.delete(id);
      }
    }
    this.edgeLayer.replaceChildren(...edges.map((e) => this.drawEdge(e)));
    const n = nodes.length;
    this.svgEl.setAttribute(
      'aria-label',
      `${n} object${n === 1 ? '' : 's'} and ${edges.length} reference${edges.length === 1 ? '' : 's'}`,
    );
  }

  private createNode(box: NodeBox): SVGGElement {
    const g = svg('g', { class: 'node', transform: `translate(${box.x} ${box.y})` });
    g.append(
      svg('title'),
      svg('rect', { class: 'node-box', width: box.w, height: box.h, rx: 8 }),
      svg('line', { class: 'node-rule', x1: 0, x2: box.w, y1: LAYOUT.headH, y2: LAYOUT.headH }),
      svg('text', { class: 'node-title', x: LAYOUT.padX, y: 15 }),
      svg('text', { class: 'node-tag', x: 2, y: -6 }),
      svg('g', { class: 'node-rows' }),
    );
    return g;
  }

  private drawEdge(e: GraphEdge): SVGGElement {
    const a = this.graph.boxes.get(e.from)!;
    const b = this.graph.boxes.get(e.to)!;
    const rightward = b.x > a.x;
    const x1 = rightward ? a.x + a.w : a.x;
    const x2 = rightward ? b.x : b.x + b.w;
    const y1 = a.y + LAYOUT.headH / 2;
    const y2 = b.y + LAYOUT.headH / 2;
    const bend = Math.max(24, Math.abs(x2 - x1) / 2) * (rightward ? 1 : -1);
    const g = svg('g', { class: 'edge' });
    g.append(
      svg('path', {
        d: `M${x1} ${y1} C${x1 + bend} ${y1} ${x2 - bend} ${y2} ${x2} ${y2}`,
        'marker-end': 'url(#vs-arrow)',
      }),
    );
    if (!e.viaItem) {
      const label = svg('text', { class: 'edge-label', x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 5 });
      label.textContent = e.field;
      g.append(label);
    }
    return g;
  }

  /** Scale the drawing down to fit the pane, but never up past its natural size. */
  private fit(box: HTMLElement): void {
    const { width, height } = this.graph;
    const cs = getComputedStyle(box);
    const room = (size: number, a: string, b: string) => size - parseFloat(a) - parseFloat(b);
    const w = room(box.clientWidth, cs.paddingLeft, cs.paddingRight);
    const h = room(box.clientHeight, cs.paddingTop, cs.paddingBottom);
    const scale = Math.min(1.25, w / width, h / height);
    if (!(scale > 0)) return;
    this.svgEl.setAttribute('width', String(Math.floor(width * scale)));
    this.svgEl.setAttribute('height', String(Math.floor(height * scale)));
  }
}
