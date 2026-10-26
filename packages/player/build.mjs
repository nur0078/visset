// Bundles the player twice: an ES module for apps, and an IIFE that the Python package inlines
// into exported HTML. The IIFE is copied into python/src/visset/_assets/.
import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';

const here = dirname(fileURLToPath(import.meta.url));
const watch = process.argv.includes('--watch');
const asset = resolve(here, '../../python/src/visset/_assets/player.js');

const common = {
  entryPoints: [resolve(here, 'src/index.ts')],
  bundle: true,
  minify: true,
  target: ['es2020', 'safari15'],
  legalComments: 'none',
  logLevel: 'info',
};

const copyPlugin = {
  name: 'copy-to-python',
  setup(build) {
    build.onEnd(async (result) => {
      if (result.errors.length) return;
      await mkdir(dirname(asset), { recursive: true });
      await copyFile(resolve(here, 'dist/visset-player.js'), asset);
    });
  },
};

const iife = {
  ...common,
  format: 'iife',
  outfile: resolve(here, 'dist/visset-player.js'),
  plugins: [copyPlugin],
};
const esm = { ...common, format: 'esm', outfile: resolve(here, 'dist/visset-player.esm.js') };

if (watch) {
  for (const options of [iife, esm]) await (await esbuild.context(options)).watch();
} else {
  await Promise.all([esbuild.build(iife), esbuild.build(esm)]);
}
