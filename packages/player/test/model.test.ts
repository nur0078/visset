import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { cpToUtf16, parseCaption, TraceModel } from '../src/model';
import type { Trace } from '../src/types';

const fixtures = resolve(dirname(fileURLToPath(import.meta.url)), '../../../schema/fixtures');
const load = (name: string) => JSON.parse(readFileSync(resolve(fixtures, name), 'utf8')) as Trace;

describe('golden traces from the Python tracer', () => {
  for (const file of readdirSync(fixtures).filter((f) => f.endsWith('.trace.json'))) {
    it(`${file}: every step resolves and formats`, () => {
      const model = new TraceModel(load(file));
      for (let i = 0; i < model.length; i++) {
        const step = model.step(i);
        expect(step.focus.length).toBeGreaterThan(0);
        for (const frame of step.stack) {
          for (const [, value] of frame.locals) {
            if ('ref' in value) expect(model.resolve(i, value)).toBeDefined();
            expect(model.format(i, value)).not.toBe('…');
          }
        }
        model.changes(i);
      }
    });
  }
});

describe('TraceModel', () => {
  const model = new TraceModel(load('python-bsearch.trace.json'));

  it('rejects unknown schemas', () => {
    expect(() => new TraceModel({ schema: 'other/1' } as unknown as Trace)).toThrow(/unsupported/);
  });

  it('formats lists inline', () => {
    const step = model.step(model.length - 1);
    const nums = step.stack[0]!.locals.find(([n]) => n === 'nums')![1];
    expect(model.format(model.length - 1, nums)).toBe('[1, 3, 5, 7, 9, 11]');
  });

  it('accumulates output and marks the fresh part', () => {
    const last = model.length - 1;
    expect(model.output(last)).toEqual({ text: 'found at 3\n', freshFrom: 0 });
    expect(model.output(0).text).toBe('');
  });

  it('reports exactly the variables that changed', () => {
    // Step "mid = (lo + hi) // 2" changes only mid in the binary_search frame.
    const i = model.trace.steps.findIndex((s) => s.caption === '`mid` becomes `2`.');
    const fid = model.step(i).stack[1]!.id;
    expect([...model.changes(i)]).toEqual([`${fid}.mid`]);
  });

  it('flags a new frame and its return value', () => {
    const call = model.trace.steps.findIndex((s) => s.kind === 'call');
    const fid = model.step(call).stack[1]!.id;
    expect(model.changes(call).has(fid)).toBe(true);
    const ret = model.trace.steps.findIndex((s) => s.kind === 'return');
    expect(model.changes(ret).has(`${fid}:return`)).toBe(true);
  });

  it('treats a nested mutation as a change of the outer variable', () => {
    const trace: Trace = {
      schema: 'visset.trace/0.1',
      meta: { language: 'test', origin: 'authored' },
      sources: [{ id: 'main', text: 'x' }],
      objects: {
        'o1@0': { type: 'list', shape: 'sequence', items: [{ ref: 'o2' }] },
        'o2@0': { type: 'list', shape: 'sequence', items: [{ p: '1', t: 'int' }] },
        'o2@1': { type: 'list', shape: 'sequence', items: [{ p: '9', t: 'int' }] },
      },
      steps: [0, 1].map((v) => ({
        kind: 'statement',
        focus: [{ source: 'main', start: [1, 0], end: [1, 1], mark: 'circle' }],
        stack: [{ id: 'f1', name: 'Global', locals: [['outer', { ref: 'o1' }]] }],
        heap: ['o1@0', `o2@${v}`],
      })),
    };
    const m = new TraceModel(trace);
    expect(m.changes(1).has('f1.outer')).toBe(true);
    expect(m.format(1, { ref: 'o1' })).toBe('[[9]]');
  });

  it('elides long containers and survives cycles', () => {
    const trace: Trace = {
      schema: 'visset.trace/0.1',
      meta: { language: 'test', origin: 'authored' },
      sources: [{ id: 'main', text: 'x' }],
      objects: {
        'o1@0': {
          type: 'list',
          shape: 'sequence',
          items: [{ ref: 'o1' }, { p: '2', t: 'int' }],
          more: 98,
        },
      },
      steps: [
        {
          kind: 'statement',
          focus: [{ source: 'main', start: [1, 0], end: [1, 1], mark: 'circle' }],
          stack: [{ id: 'f1', name: 'Global', locals: [['a', { ref: 'o1' }]] }],
          heap: ['o1@0'],
        },
      ],
    };
    expect(new TraceModel(trace).format(0, { ref: 'o1' })).toBe('[[…], 2, … 98 more]');
  });
});

describe('helpers', () => {
  it('splits captions into text and code', () => {
    expect(parseCaption('`x` becomes `2`.')).toEqual([
      { code: true, text: 'x' },
      { code: false, text: ' becomes ' },
      { code: true, text: '2' },
      { code: false, text: '.' },
    ]);
  });

  it('converts code point columns to UTF-16 offsets', () => {
    expect(cpToUtf16('a😀b', 2)).toBe(3); // the emoji is 2 UTF-16 units but 1 code point
    expect(cpToUtf16('abc', 2)).toBe(2);
  });
});
