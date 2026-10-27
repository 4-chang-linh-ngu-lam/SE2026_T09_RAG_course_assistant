import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
export async function findFixtureLeaks(directory) {
  const leaks = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) leaks.push(...await findFixtureLeaks(path));
    else if (/\.(js|json|html|map)$/.test(entry.name) && (await readFile(path, 'utf8')).includes('__LUMI_PREVIEW_FIXTURE_CANARY_')) leaks.push(path);
  }
  return leaks;
}
