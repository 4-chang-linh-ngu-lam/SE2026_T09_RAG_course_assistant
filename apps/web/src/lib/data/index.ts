// The ONLY adapter selection import. Webpack selects live or dev mock at build time.
// No per-feature fallback, no query/localStorage switch, no client-side API keys.
import { adapter as selectedAdapter } from '@data-adapter';
import { assertDataSource } from '../../../config/data-mode.mjs';
export type { DataAdapter } from './port';
export const dataMode: 'live' | 'mock' = process.env.NEXT_PUBLIC_DATA_MODE === 'mock' ? 'mock' : 'live';
assertDataSource(dataMode, selectedAdapter.source, process.env.NODE_ENV === 'production');
if (process.env.NODE_ENV === 'production' && selectedAdapter.fixtureSignature) throw new Error('Fixture-bearing adapter cannot run in production');
export const adapter = selectedAdapter;
