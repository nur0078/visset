import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ObjectGraph, shortFloat } from '../src/graph';
import { TraceModel } from '../src/model';
import type { HeapObject, Trace, Value } from '../src/types';

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), '../../../schema/fixtures');
const load = (name: string) =>
  new TraceModel(JSON.parse(readFileSync(resolve(fixtures, name), 'utf8')) as Trace);

/** One-step trace whose only frame names every object in `objects`. */
function oneStep(objects: Record<string, HeapObject>): TraceModel {
  return new TraceModel({
    schema: 'visset.trace/0.1',
    meta: { language: 'test', origin: 'authored' },
    sources: [{ id: 'main', text: 'x' }],
    objects,
    steps: [
      {
        kind: 'statement',
        focus: [{ source: 'main', start: [1, 0], end: [1, 1], mark: 'circle' }],
        stack: [
          {
            id: 'f1',
            name: 'Global',
            locals: Object.keys(objects).map((vid) => [
              vid.split('@')[0]!,
              { ref: vid.split('@')[0]! },
            ]),
          },
        ],
        heap: Object.keys(objects),
      },
    ],
  });
}

const node = (fields: [string, Value][]): HeapObject => ({ type: 'Node', shape: 'record', fields });

describe('ObjectGraph', () => {
  it('finds no graph in traces without linked objects', () => {
    for (const f of ['bsearch', 'fib', 'two_pointers', 'word_count']) {
      expect(ObjectGraph.build(load(`python-${f}.trace.json`)), f).toBeNull();
    }
  });

  it('draws an autograd graph from _prev sets, with no knowledge of the class', () => {
    const model = load('python-autograd.trace.json');
    const graph = ObjectGraph.build(model)!;
    expect(graph.boxes.size).toBe(6); // x, w, b, x*w, n, o
    const last = graph.at(model.length - 1);
    const byTitle = new Map(last.nodes.map((n) => [n.title || n.type, n]));
    expect([...byTitle.keys()].sort()).toEqual(['Value', 'b', 'n', 'o', 'w', 'x']);
    expect(last.edges.every((e) => e.field === '_prev' && e.viaItem)).toBe(true);
    expect(last.edges).toHaveLength(5);
    // Simple fields become rows; functions, empty strings and the link set do not.
    const o = byTitle.get('o')!;
    expect(o.rows.map(([k]) => k)).toEqual(['data', 'grad', '_op']);
    expect(o.rows.find(([k]) => k === 'grad')![1]).toBe('1.0');
    expect(byTitle.get('x')!.rows.map(([k, v]) => `${k}=${v}`)).toEqual([
      'data=2.0',
      'grad=-1.503',
    ]);
    // Inputs sit left of what they feed; nodes never move between steps.
    const box = (t: string) => graph.boxes.get(byTitle.get(t)!.id)!;
    expect(box('x').x).toBeLessThan(box('n').x);
    expect(box('n').x).toBeLessThan(box('o').x);
    expect(box('b').x).toBeGreaterThan(box('x').x); // pulled next to `n`, which uses it
  });

  it('shows objects as the forward pass creates them', () => {
    const model = load('python-autograd.trace.json');
    const graph = ObjectGraph.build(model)!;
    const counts = model.trace.steps.map((_, i) => graph.at(i).nodes.length);
    expect(counts[0]).toBe(0);
    expect(Math.max(...counts)).toBe(6);
    for (let i = 1; i < counts.length; i++)
      expect(counts[i]!).toBeGreaterThanOrEqual(counts[i - 1]!);
  });

  it('labels direct links and names objects after the variables that hold them', () => {
    const graph = ObjectGraph.build(
      oneStep({
        'o1@0': node([
          ['val', { p: '1', t: 'int' }],
          ['next', { ref: 'o2' }],
        ]),
        'o2@0': node([
          ['val', { p: '2', t: 'int' }],
          ['next', { p: 'None', t: 'None' }],
        ]),
      }),
    )!;
    const { nodes, edges } = graph.at(0);
    expect(edges).toEqual([{ from: 'o1', to: 'o2', field: 'next', viaItem: false }]);
    expect(nodes.map((n) => n.names)).toEqual([['o1'], ['o2']]);
    expect(nodes[1]!.rows.map(([k]) => k)).toEqual(['val']); // None is left out
    expect(graph.boxes.get('o1')!.x).toBeLessThan(graph.boxes.get('o2')!.x);
  });

  it('handles cycles (a doubly linked pair)', () => {
    const graph = ObjectGraph.build(
      oneStep({
        'o1@0': node([['next', { ref: 'o2' }]]),
        'o2@0': node([['prev', { ref: 'o1' }]]),
      }),
    )!;
    expect(graph.at(0).edges).toHaveLength(2);
    expect(graph.boxes.get('o1')!.x).not.toBe(graph.boxes.get('o2')!.x);
  });
});

describe('shortFloat', () => {
  it('keeps floats short but still float-looking', () => {
    expect(shortFloat('0.8799999999999999')).toBe('0.88');
    expect(shortFloat('-1.5029152313085248')).toBe('-1.503');
    expect(shortFloat('2.0')).toBe('2.0');
    expect(shortFloat('0.0')).toBe('0.0');
    expect(shortFloat('1e-09')).toBe('1e-9');
    expect(shortFloat('nan')).toBe('nan');
  });
});
