import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
if (process.env.NODE_ENV === 'production') throw new Error('Preview is development-only');
const args = process.argv.slice(2);
const webpack = args.includes('--webpack');
if (webpack && args.some(arg => arg === '--turbo' || arg === '--turbopack')) throw new Error('Choose one development bundler.');
const forwarded = args.filter(arg => arg !== '--webpack' && arg !== '--turbo' && arg !== '--turbopack');
const child = spawn(process.execPath, [require.resolve('next/dist/bin/next'), 'dev', ...(webpack ? [] : ['--turbopack']), ...forwarded], {
  stdio: 'inherit', env: { ...process.env, NEXT_PUBLIC_DATA_MODE: 'mock' },
});
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
