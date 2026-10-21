import { fileURLToPath } from 'node:url';
import { resolveDataMode } from './config/data-mode.mjs';

export default function configure(phase) {
  const production = process.env.NODE_ENV === 'production' || phase === 'phase-production-build' || phase === 'phase-production-server';
  const mode = resolveDataMode(process.env.NEXT_PUBLIC_DATA_MODE ?? 'live', production);
  const adapter = mode === 'mock' ? './dev/mocks/adapter.ts' : './src/lib/data/live.ts';
  return {
    distDir: mode === 'mock' ? '.next-preview' : '.next',
    poweredByHeader: false,
    env: { NEXT_PUBLIC_DATA_MODE: mode },
    turbopack: {
      root: fileURLToPath(new URL('.', import.meta.url)),
      // Turbopack does not execute webpack(); keep both bundlers on the same adapter.
      resolveAlias: { '@data-adapter': adapter },
    },
    webpack(config) {
      config.resolve.alias['@data-adapter$'] = fileURLToPath(new URL(adapter, import.meta.url));
      return config;
    },
  };
}
