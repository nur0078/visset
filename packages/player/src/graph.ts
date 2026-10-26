import type { TraceModel } from './model';
import type { HeapObject, Value } from './types';

/**
 * Objects that point at each other, found from the trace's shapes alone: a `record` whose field
 * refers to another record, directly (`node.next`) or through a sequence, set or mapping
 * (`value._prev = {a, b}`), is a node with arrows. Nothing here knows any class or language, so
 * linked lists, trees and autograd graphs all come out of the same rules.
 *
 * The layout is computed once for the whole trace, so a node stays where it is from the step it
 * appears to the last step. Columns follow creation order (older objects to the left), which
 * keeps every arrow between columns and the layout acyclic even when objects point both ways.
 */

export interface GraphEdge {
  from: string;
  to: string;
  /** The field holding the reference, e.g. `next` or `_prev`. */
  field: string;
  /** True when the reference goes through a container (`_prev = {a, b}`), not a direct field. */
  viaItem: boolean;
}

export interface NodeBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface NodeView {
  id: string;
  type: string;
  /** A `label`/`name` field, when the object has a non-empty one; shown as the node's title. */
  title: string;
  rows: [name: string, display: string, full: string][];
  /** Names in the innermost frame that refer to this object. */
  names: string[];
}

export const LAYOUT = {
  charW: 7.4, // ui-monospace at 12px; wide enough that labels never touch the border
  rowH: 18,
  headH: 22,
  padX: 10,
  padY: 6,
  tagH: 18, // room above each node for variable names
  colGap: 44,
  rowGap: 14,
  margin: 8,
  minW: 64,
  maxRows: 8,
  maxNodes: 80,
};

const TITLE_FIELDS = ['label', 'name'];
const CONTAINERS = new Set(['sequence', 'set', 'mapping']);

export class ObjectGraph {
  readonly boxes = new Map<string, NodeBox>();
  width = 0;
  height = 0;

  private constructor(private readonly model: TraceModel) {}

  /** The graph for a trace, or null when no object links to another object. */
  static build(model: TraceModel): ObjectGraph | null {
    const g = new ObjectGraph(model);
    return g.layout() ? g : null;
  }

  /** The visible nodes and arrows at step i. */
  at(i: number): { nodes: NodeView[]; edges: GraphEdge[] } {
    const step = this.model.step(i);
    const visible = new Map<string, HeapObject>();
    for (const vid of step.heap) {
      const oid = vid.slice(0, vid.lastIndexOf('@'));
      const obj = this.model.trace.objects[vid];
      if (this.boxes.has(oid) && obj?.fields?.length) visible.set(oid, obj);
    }
    const names = new Map<string, string[]>();
    const top = step.stack[step.stack.length - 1];
    for (const [name, value] of top?.locals ?? []) {
      if ('ref' in value && visible.has(value.ref)) {
        names.set(value.ref, [...(names.get(value.ref) ?? []), name]);
      }
    }
    const edges: GraphEdge[] = [];
    const nodes: NodeView[] = [];
    for (const [oid, obj] of visible) {
      for (const e of this.edgesOf(oid, obj, (v) => this.model.resolve(i, v))) {
        if (visible.has(e.to)) edges.push(e);
      }
      nodes.push({
        id: oid,
        ...describe(obj, (v) => this.model.resolve(i, v)),
        names: names.get(oid) ?? [],
      });
    }
    return { nodes, edges };
  }

  // ------------------------------------------------------------------ layout

  private layout(): boolean {
    const objects = this.model.trace.objects;
    // Every version of every object, by object id, in the order they first appear (creation order).
    const versions = new Map<string, HeapObject[]>();
    for (const [vid, obj] of Object.entries(objects)) {
      const oid = vid.slice(0, vid.lastIndexOf('@'));
      const list = versions.get(oid);
      if (list) list.push(obj);
      else versions.set(oid, [obj]);
    }
    const isRecord = (oid: string) => versions.get(oid)?.[0]?.shape === 'record';
    // Union over all versions: an over-approximation is fine for placing nodes.
    const anyVersion = (v: Value): HeapObject[] => ('ref' in v ? (versions.get(v.ref) ?? []) : []);
    const union = new Map<string, Set<string>>(); // undirected neighbours
    const link = (a: string, b: string) => {
      if (a === b) return;
      for (const [x, y] of [
        [a, b],
        [b, a],
      ] as const) {
        const set = union.get(x) ?? new Set();
        set.add(y);
        union.set(x, set);
      }
    };
    for (const [oid, list] of versions) {
      if (!isRecord(oid)) continue;
      for (const obj of list) {
        for (const e of this.edgesOf(oid, obj, anyVersion, isRecord)) link(oid, e.to);
      }
    }
    if (!union.size || union.size > LAYOUT.maxNodes) return false;

    const age = new Map([...versions.keys()].map((oid, n) => [oid, n]));
    const ids = [...union.keys()].sort((a, b) => age.get(a)! - age.get(b)!);

    // Columns: one past the newest older neighbour.
    const col = new Map<string, number>();
    for (const id of ids) {
      let c = 0;
      for (const n of union.get(id)!) {
        if (age.get(n)! < age.get(id)! && col.has(n)) c = Math.max(c, col.get(n)! + 1);
      }
      col.set(id, c);
    }
    // Then pull each object right, next to the newest object that refers to it, so an input
    // that joins late (the `b` in `x*w + b`) sits beside its user instead of far to the left.
    for (const id of [...ids].reverse()) {
      const newer = [...union.get(id)!].filter((n) => age.get(n)! > age.get(id)!);
      if (newer.length)
        col.set(id, Math.max(col.get(id)!, Math.min(...newer.map((n) => col.get(n)!)) - 1));
    }
    const columns: string[][] = [];
    for (const id of ids) {
      const c = col.get(id)!;
      columns[c] = [...(columns[c] ?? []), id];
    }

    // Fewer crossings: order each column by the mean position of its neighbours, a few sweeps.
    const pos = new Map<string, number>();
    const place = (c: string[]) => {
      c.forEach((id, n) => {
        pos.set(id, n / Math.max(1, c.length - 1));
      });
    };
    for (const c of columns) place(c);
    for (let sweep = 0; sweep < 4; sweep++) {
      const order = sweep % 2 ? [...columns].reverse() : columns;
      for (const c of order) {
        const score = new Map(
          c.map((id) => {
            const ns = [...union.get(id)!].filter((n) => col.get(n) !== col.get(id));
            const mean = ns.length
              ? ns.reduce((s, n) => s + pos.get(n)!, 0) / ns.length
              : pos.get(id)!;
            return [id, mean];
          }),
        );
        c.sort((a, b) => score.get(a)! - score.get(b)! || age.get(a)! - age.get(b)!);
        place(c);
      }
    }

    // Sizes: the largest any version of the node gets, so a node never resizes mid-walkthrough.
    const size = new Map<string, [number, number]>();
    for (const id of ids) {
      let w = LAYOUT.minW;
      let rows = 0;
      for (const obj of versions.get(id)!) {
        const d = describe(obj, (v) => anyVersion(v)[0]);
        rows = Math.max(rows, d.rows.length);
        w = Math.max(w, textW(d.title || d.type, 1.05));
        for (const [name, display] of d.rows) w = Math.max(w, textW(`${name}  ${display}`));
      }
      size.set(id, [Math.ceil(w), LAYOUT.headH + rows * LAYOUT.rowH + LAYOUT.padY]);
    }

    const colW = columns.map((c) => Math.max(...c.map((id) => size.get(id)![0])));
    const colH = columns.map(
      (c) =>
        c.reduce((s, id) => s + size.get(id)![1] + LAYOUT.tagH, 0) + (c.length - 1) * LAYOUT.rowGap,
    );
    const height = Math.max(...colH);
    let x = LAYOUT.margin;
    columns.forEach((c, n) => {
      let y = LAYOUT.margin + (height - colH[n]!) / 2;
      for (const id of c) {
        const [w, h] = size.get(id)!;
        y += LAYOUT.tagH;
        this.boxes.set(id, { id, x: x + (colW[n]! - w) / 2, y, w, h });
        y += h + LAYOUT.rowGap;
      }
      x += colW[n]! + LAYOUT.colGap;
    });
    this.width = x - LAYOUT.colGap + LAYOUT.margin;
    this.height = height + 2 * LAYOUT.margin;
    return true;
  }

  private edgesOf(
    oid: string,
    obj: HeapObject,
    resolve: (v: Value) => HeapObject | HeapObject[] | undefined,
    isRecord: (oid: string) => boolean = (id) => this.boxes.has(id),
  ): GraphEdge[] {
    const out: GraphEdge[] = [];
    const seen = new Set<string>();
    const add = (to: string, field: string, viaItem: boolean) => {
      if (to !== oid && !seen.has(`${field}>${to}`) && isRecord(to)) {
        seen.add(`${field}>${to}`);
        out.push({ from: oid, to, field, viaItem });
      }
    };
    for (const [field, value] of obj.fields ?? []) {
      if (!('ref' in value)) continue;
      add(value.ref, field, false);
      const got = resolve(value);
      for (const inner of Array.isArray(got) ? got : got ? [got] : []) {
        if (!CONTAINERS.has(inner.shape)) continue;
        for (const v of containerValues(inner)) if ('ref' in v) add(v.ref, field, true);
      }
    }
    return out;
  }
}

function containerValues(obj: HeapObject): Value[] {
  return [...(obj.items ?? []), ...(obj.entries ?? []).flat()];
}

/** What a node shows: its simple fields. References become arrows; functions and blanks are left out. */
function describe(
  obj: HeapObject,
  resolve: (v: Value) => HeapObject | undefined,
): Omit<NodeView, 'id' | 'names'> {
  let title = '';
  const rows: NodeView['rows'] = [];
  for (const [name, value] of obj.fields ?? []) {
    if ('ref' in value) {
      // Linking fields are drawn as arrows; other objects (functions, empty sets) are noise here.
      const target = resolve(value);
      if (target?.shape === 'opaque' && target.repr)
        rows.push([name, clip(target.repr), target.repr]);
      continue;
    }
    if (value.p === "''" || value.p === '""' || value.t === 'None') continue;
    if (!title && value.t === 'str' && TITLE_FIELDS.includes(name)) {
      title = unquote(value.p);
      continue;
    }
    rows.push([name, value.t === 'float' ? shortFloat(value.p) : clip(value.p), value.p]);
  }
  return { type: obj.type, title, rows: rows.slice(0, LAYOUT.maxRows) };
}

/** `0.8799999999999999` → `0.88`, `-1.5029152313085248` → `-1.503`. Big and tiny numbers keep their exponent. */
export function shortFloat(p: string): string {
  const n = Number(p);
  if (!Number.isFinite(n) || n === 0) return p;
  const a = Math.abs(n);
  if (a >= 1e6 || a < 1e-4) return n.toExponential(3).replace(/\.?0+e/, 'e');
  const s = n.toPrecision(4);
  if (!s.includes('.')) return s;
  const short = s.replace(/0+$/, '');
  return short.endsWith('.') ? `${short}0` : short;
}

function unquote(p: string): string {
  return /^(['"]).*\1$/s.test(p) ? p.slice(1, -1) : p;
}

function clip(text: string, max = 24): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function textW(text: string, scale = 1): number {
  return text.length * LAYOUT.charW * scale + 2 * LAYOUT.padX;
}
