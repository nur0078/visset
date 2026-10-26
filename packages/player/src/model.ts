import type { Frame, HeapObject, Step, Trace, Value } from './types';

const SCHEMA_PREFIX = 'visset.trace/0.';

/**
 * Read-only view over a trace with the derived data the UI needs: cumulative output,
 * object lookup per step, and which values changed. Everything is computed per step on
 * demand and cached, so opening a 10k-step trace costs nothing until you scrub to a step.
 */
export class TraceModel {
  readonly trace: Trace;
  readonly length: number;
  private readonly outEnds: number[] = [];
  private readonly allOut: string;
  private readonly versionMaps = new Map<number, Map<string, string>>();
  private readonly changeCache = new Map<number, Set<string>>();

  constructor(trace: Trace) {
    if (!trace || typeof trace.schema !== 'string' || !trace.schema.startsWith(SCHEMA_PREFIX)) {
      throw new Error(`visset: unsupported trace (schema ${String(trace?.schema)})`);
    }
    this.trace = trace;
    this.length = trace.steps.length;
    let out = '';
    for (const step of trace.steps) {
      out += step.stdout ?? '';
      this.outEnds.push(out.length);
    }
    this.allOut = out;
  }

  step(i: number): Step {
    const step = this.trace.steps[i];
    if (!step) throw new RangeError(`step ${i} out of range`);
    return step;
  }

  /** Everything printed up to and including step i, and where step i's own output starts. */
  output(i: number): { text: string; freshFrom: number } {
    const end = this.outEnds[i] ?? 0;
    const start = i > 0 ? (this.outEnds[i - 1] ?? 0) : 0;
    return { text: this.allOut.slice(0, end), freshFrom: start };
  }

  /** The object a reference points to, as it was at step i. */
  resolve(i: number, value: Value): HeapObject | undefined {
    if (!('ref' in value)) return undefined;
    const vid = this.versions(i).get(value.ref);
    return vid ? this.trace.objects[vid] : undefined;
  }

  private versions(i: number): Map<string, string> {
    let map = this.versionMaps.get(i);
    if (!map) {
      map = new Map();
      for (const vid of this.step(i).heap) map.set(vid.slice(0, vid.lastIndexOf('@')), vid);
      this.versionMaps.set(i, map);
    }
    return map;
  }

  /** Compact inline text for a value, e.g. `[1, 3, 5, …]` or `Node(val=1, next=Node(…))`. */
  format(i: number, value: Value, budget = 80): string {
    const text = this.fmt(i, value, 0, new Set());
    return text.length > budget ? `${text.slice(0, budget - 1)}…` : text;
  }

  private fmt(i: number, value: Value, depth: number, seen: Set<string>): string {
    if ('p' in value) return value.p;
    const obj = this.resolve(i, value);
    if (!obj) return '…';
    if (seen.has(value.ref)) return obj.shape === 'sequence' ? '[…]' : '{…}';
    const nested = depth >= 3 && ['sequence', 'mapping', 'set', 'record'].includes(obj.shape);
    if (nested) return '…';
    seen.add(value.ref);
    const inner = (v: Value) => this.fmt(i, v, depth + 1, seen);
    const more = obj.more ? `, … ${obj.more} more` : '';
    let text: string;
    switch (obj.shape) {
      case 'sequence': {
        const body = (obj.items ?? []).map(inner).join(', ') + more;
        text =
          obj.type === 'tuple' ? `(${body}${obj.items?.length === 1 ? ',' : ''})` : `[${body}]`;
        break;
      }
      case 'set':
        text =
          (obj.items?.length ?? 0) === 0
            ? `${obj.type}()`
            : `{${(obj.items ?? []).map(inner).join(', ')}${more}}`;
        break;
      case 'mapping':
        text = `{${(obj.entries ?? []).map(([k, v]) => `${inner(k)}: ${inner(v)}`).join(', ')}${more}}`;
        break;
      case 'record':
        text = `${obj.type}(${(obj.fields ?? []).map(([k, v]) => `${k}=${inner(v)}`).join(', ')})`;
        break;
      case 'function':
        text = `ƒ ${obj.repr ?? obj.type}`;
        break;
      case 'class':
        text = `class ${obj.repr ?? obj.type}`;
        break;
      default:
        text = obj.repr ?? obj.type;
    }
    seen.delete(value.ref);
    return text;
  }

  /**
   * What changed at step i, as paths: `<frameId>.<name>` for locals, `<frameId>` for a frame
   * that just appeared, `<frameId>:return` for a return value. A reference counts as changed
   * when anything reachable from it got a new version, so `head.next.val = 9` marks `head`.
   * Authored steps may list `changes` explicitly; that wins.
   */
  changes(i: number): Set<string> {
    const cached = this.changeCache.get(i);
    if (cached) return cached;
    const step = this.step(i);
    let out: Set<string>;
    if (step.changes) {
      out = new Set(step.changes);
    } else if (i === 0) {
      out = new Set(step.stack.flatMap((f) => f.locals.map(([n]) => `${f.id}.${n}`)));
    } else {
      out = this.diff(i - 1, i);
    }
    this.changeCache.set(i, out);
    return out;
  }

  private diff(a: number, b: number): Set<string> {
    const out = new Set<string>();
    const before = new Map<string, Frame>(this.step(a).stack.map((f) => [f.id, f]));
    for (const frame of this.step(b).stack) {
      const old = before.get(frame.id);
      if (!old) out.add(frame.id);
      const oldLocals = new Map(old?.locals ?? []);
      for (const [name, value] of frame.locals) {
        const prev = oldLocals.get(name);
        if (
          !prev ||
          !sameValue(prev, value) ||
          this.signature(a, value) !== this.signature(b, value)
        ) {
          out.add(`${frame.id}.${name}`);
        }
      }
      if (frame.returnValue || frame.yieldValue) out.add(`${frame.id}:return`);
    }
    return out;
  }

  /** The versions of every object reachable from a value (bounded), as a comparable string. */
  private signature(i: number, value: Value): string {
    if (!('ref' in value)) return '';
    const map = this.versions(i);
    const parts: string[] = [];
    const todo = [value.ref];
    const seen = new Set<string>();
    while (todo.length && seen.size < 200) {
      const oid = todo.pop()!;
      if (seen.has(oid)) continue;
      seen.add(oid);
      const vid = map.get(oid);
      parts.push(vid ?? oid);
      const obj = vid ? this.trace.objects[vid] : undefined;
      if (obj) for (const child of childRefs(obj)) todo.push(child);
    }
    return parts.sort().join('|');
  }
}

export function sameValue(a: Value, b: Value): boolean {
  if ('ref' in a || 'ref' in b) return 'ref' in a && 'ref' in b && a.ref === b.ref;
  return a.p === b.p && a.t === b.t;
}

function childRefs(obj: HeapObject): string[] {
  const out: string[] = [];
  const add = (v: Value) => {
    if ('ref' in v) out.push(v.ref);
  };
  for (const v of obj.items ?? []) add(v);
  for (const [k, v] of obj.entries ?? []) {
    add(k);
    add(v);
  }
  for (const [, v] of obj.fields ?? []) add(v);
  return out;
}

/** Split a caption into text and `code` runs. */
export function parseCaption(text: string): { code: boolean; text: string }[] {
  const parts: { code: boolean; text: string }[] = [];
  const re = /`([^`]+)`/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) parts.push({ code: false, text: text.slice(last, m.index) });
    parts.push({ code: true, text: m[1] ?? '' });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ code: false, text: text.slice(last) });
  return parts;
}

/** Convert a code point column to a UTF-16 offset within `line` (JS strings are UTF-16). */
export function cpToUtf16(line: string, col: number): number {
  let units = 0;
  let cps = 0;
  for (const ch of line) {
    if (cps >= col) break;
    units += ch.length;
    cps += 1;
  }
  return units;
}
