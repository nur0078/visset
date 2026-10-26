// Drives the built player in a real browser. Run `pnpm build` first.
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { type Browser, chromium, type Page } from 'playwright';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = resolve(here, '../../../schema/fixtures');
const bundle = readFileSync(resolve(here, '../dist/visset-player.js'), 'utf8');

let browser: Browser;
beforeAll(async () => {
  browser = await chromium.launch();
});
afterAll(async () => {
  await browser?.close();
});

async function open(
  trace: string,
  opts: { reducedMotion?: boolean } = {},
): Promise<{ page: Page; errors: string[] }> {
  const page = await browser.newPage({
    viewport: { width: 1100, height: 700 },
    reducedMotion: opts.reducedMotion ? 'reduce' : 'no-preference',
  });
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  const safe = trace.replace(/</g, '\\u003c');
  await page.setContent(
    `<!doctype html><body><visset-player global-keys style="height:600px"><script type="application/json">${safe}</script></visset-player><script>${bundle}</script></body>`,
  );
  await page.waitForFunction(() =>
    document.querySelector('visset-player')?.shadowRoot?.querySelector('.mark'),
  );
  return { page, errors };
}

/** For the current step: is every mark drawn over the rows it claims to focus? */
function markGeometry(page: Page) {
  return page.evaluate(() => {
    const host = document.querySelector('visset-player')!;
    const root = host.shadowRoot!;
    const marks = [...root.querySelectorAll<SVGGElement>('.marks .mark')].map((g) =>
      g.getBoundingClientRect(),
    );
    const rows = [...root.querySelectorAll<HTMLElement>('.line.active')].map((r) =>
      r.getBoundingClientRect(),
    );
    return { marks: marks.map((m) => [m.top, m.bottom]), rows: rows.map((r) => [r.top, r.bottom]) };
  });
}

describe('player in a browser', () => {
  for (const file of readdirSync(fixtures).filter((f) => f.endsWith('.trace.json'))) {
    it(`${file}: every step draws a mark on the focused line`, async () => {
      const text = readFileSync(resolve(fixtures, file), 'utf8');
      const steps = (JSON.parse(text) as { steps: unknown[] }).steps.length;
      const { page, errors } = await open(text, { reducedMotion: true });
      for (let i = 0; i < steps; i++) {
        if (i > 0) await page.keyboard.press('ArrowRight');
        const { marks, rows } = await markGeometry(page);
        expect(marks.length, `step ${i}`).toBeGreaterThan(0);
        const [rowTop, rowBottom] = [
          Math.min(...rows.map((r) => r[0]!)),
          Math.max(...rows.map((r) => r[1]!)),
        ];
        for (const [top, bottom] of marks) {
          // The mark must overlap the focused rows (a circle may overhang a little).
          expect(bottom!, `step ${i}`).toBeGreaterThan(rowTop);
          expect(top!, `step ${i}`).toBeLessThan(rowBottom);
        }
      }
      expect(await page.evaluate(() => document.querySelector('visset-player')!.index)).toBe(
        steps - 1,
      );
      expect(errors).toEqual([]);
      await page.close();
    });
  }

  it('keyboard: Home/End, Space plays, slider seeks', async () => {
    const { page, errors } = await open(
      readFileSync(resolve(fixtures, 'python-bsearch.trace.json'), 'utf8'),
    );
    const index = () => page.evaluate(() => document.querySelector('visset-player')!.index);
    await page.keyboard.press('End');
    expect(await index()).toBe(19);
    await page.keyboard.press('Home');
    expect(await index()).toBe(0);
    await page.evaluate(() => document.querySelector('visset-player')!.setSpeed(3));
    await page.keyboard.press(' ');
    await page.waitForTimeout(1000);
    await page.keyboard.press(' ');
    const played = await index();
    expect(played).toBeGreaterThan(0);
    await page.waitForTimeout(600);
    expect(await index()).toBe(played); // paused
    const counter = await page.evaluate(
      () =>
        document.querySelector('visset-player')!.shadowRoot!.querySelector('.counter')!.textContent,
    );
    expect(counter).toBe(`${played + 1} / 20`);
    expect(errors).toEqual([]);
    await page.close();
  });

  it('shows the error notice at the end of a failing program', async () => {
    const trace = JSON.parse(readFileSync(resolve(fixtures, 'python-fib.trace.json'), 'utf8'));
    trace.meta.error = { type: 'KeyError', message: "'k'", line: 3 };
    const { page } = await open(JSON.stringify(trace));
    await page.keyboard.press('End');
    const notice = await page.evaluate(() => {
      const n = document
        .querySelector('visset-player')!
        .shadowRoot!.querySelector<HTMLElement>('.notice')!;
      return n.hidden ? null : n.textContent;
    });
    expect(notice).toBe("The program stopped with KeyError on line 3: 'k'");
    await page.close();
  });

  it('numbers an excerpt with its original line numbers', async () => {
    const trace = JSON.parse(readFileSync(resolve(fixtures, 'python-fib.trace.json'), 'utf8'));
    trace.sources[0].firstLine = 12;
    const { page } = await open(JSON.stringify(trace));
    const numbers = await page.evaluate(() =>
      [...document.querySelector('visset-player')!.shadowRoot!.querySelectorAll('.ln')].map(
        (n) => n.textContent,
      ),
    );
    expect(numbers.slice(0, 3)).toEqual(['12', '13', '14']);
    await page.close();
  });

  it('escapes source text instead of injecting it as HTML', async () => {
    const trace = JSON.parse(readFileSync(resolve(fixtures, 'python-fib.trace.json'), 'utf8'));
    trace.sources[0].text = `<img src=x onerror="window.pwned=1">\n${trace.sources[0].text}`;
    trace.steps[0].caption = '<b>bold</b> `<i>`';
    const { page } = await open(JSON.stringify(trace));
    expect(
      await page.evaluate(() => (window as unknown as { pwned?: number }).pwned),
    ).toBeUndefined();
    const caption = await page.evaluate(
      () =>
        document.querySelector('visset-player')!.shadowRoot!.querySelector('.caption')!.innerHTML,
    );
    expect(caption).toBe('&lt;b&gt;bold&lt;/b&gt; <code>&lt;i&gt;</code>');
    await page.close();
  });
  it('draws linked objects as a graph, and pulses the field that changed', async () => {
    const text = readFileSync(resolve(fixtures, 'python-autograd.trace.json'), 'utf8');
    const steps = (JSON.parse(text) as { steps: { caption: string }[] }).steps;
    const target = steps.findIndex((s) => s.caption.startsWith('`other.grad` becomes'));
    const { page, errors } = await open(text);
    await page.evaluate((i) => document.querySelector('visset-player')!.goTo(i), target);
    const view = await page.evaluate(() => {
      const root = document.querySelector('visset-player')!.shadowRoot!;
      const svg = root.querySelector<SVGSVGElement>('.graph-svg')!;
      const box = svg.getBoundingClientRect();
      const nodes = [...root.querySelectorAll<SVGGElement>('.graph .node')];
      return {
        nodes: nodes.length,
        edges: root.querySelectorAll('.graph .edge').length,
        changed: [...root.querySelectorAll('.node-row.changed')].map(
          (r) =>
            `${r.querySelector('.row-name')!.textContent}=${r.querySelector('.row-value')!.firstChild!.textContent}`,
        ),
        inside: nodes.every((n) => {
          const r = n.getBoundingClientRect();
          return r.left >= box.left - 1 && r.right <= box.right + 1;
        }),
      };
    });
    expect(view.nodes).toBe(6);
    expect(view.edges).toBe(5);
    expect(view.changed).toEqual(['grad=0.501']);
    expect(view.inside).toBe(true);
    expect(errors).toEqual([]);
    await page.close();
  });

  it('shows no graph pane when nothing links to anything', async () => {
    const { page } = await open(
      readFileSync(resolve(fixtures, 'python-bsearch.trace.json'), 'utf8'),
    );
    const graphs = await page.evaluate(
      () => document.querySelector('visset-player')!.shadowRoot!.querySelectorAll('.graph').length,
    );
    expect(graphs).toBe(0);
    await page.close();
  });
});
