import { readdir, readFile } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { inspectSource } from './boundary-policy.mjs';
const root = process.cwd(), failures = [];
async function scan(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) await scan(path);
    else if (/\.[cm]?[jt]sx?$/.test(entry.name)) failures.push(...inspectSource(relative(root, path).replaceAll('\\', '/'), await readFile(path, 'utf8')));
  }
}
for (const dir of ['src', 'app']) await scan(join(root, dir));
if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; } else console.log('Product import/network/storage boundaries passed.');
