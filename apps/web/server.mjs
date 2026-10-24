import { createServer } from 'node:http';
import { parseArgs } from 'node:util';
import next from 'next';
import nextEnv from '@next/env';
import { attestClientRequest } from './config/client-identity.mjs';
import { resolveDataMode } from './config/data-mode.mjs';

const { values } = parseArgs({ options: {
  dev: { type: 'boolean', default: false },
  hostname: { type: 'string', short: 'H' },
  port: { type: 'string', short: 'p' },
  turbopack: { type: 'boolean', default: false },
} });
const dev = values.dev;
process.env.NODE_ENV ??= dev ? 'development' : 'production';
nextEnv.loadEnvConfig(process.cwd(), dev);
resolveDataMode(process.env.NEXT_PUBLIC_DATA_MODE ?? 'live', !dev);
const secret = process.env.CORE_PROXY_SECRET;
if (!secret || secret.length < 32) throw new Error('Configure server-only CORE_PROXY_SECRET (at least 32 characters) in Web and Core.');
const hostname = values.hostname ?? (dev ? 'localhost' : '0.0.0.0');
const port = Number(values.port ?? process.env.PORT ?? 3000);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid port');
const app = next({ dev, hostname, port, turbopack: values.turbopack });
await app.prepare();
const handle = app.getRequestHandler();
const server = createServer((request, response) => {
  try { attestClientRequest(request, secret); }
  catch { response.writeHead(400, { 'Cache-Control': 'no-store' }); response.end(); return; }
  void handle(request, response).catch(() => {
    if (!response.headersSent) response.writeHead(500, { 'Cache-Control': 'no-store' });
    response.end();
  });
});
// Next attaches its WebSocket handler on the first HTTP request (including HMR).
// Registering another upgrade handler here would handle the same socket twice.
server.listen(port, hostname, () => console.log(`Lumi Web ready: http://${hostname}:${port}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  server.close(() => { void app.close().finally(() => process.exit(0)); });
  server.closeAllConnections();
});
