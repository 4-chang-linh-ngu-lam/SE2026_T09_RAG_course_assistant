import { assertDataSource, resolveDataMode } from '../config/data-mode.mjs';
import { findFixtureLeaks } from './release-policy.mjs';
resolveDataMode(process.env.NEXT_PUBLIC_DATA_MODE ?? 'live', true);
const leaks = [...await findFixtureLeaks('.next/static'), ...await findFixtureLeaks('.next/server')];
if (leaks.length) { console.error('Preview data found in release output:', leaks); process.exitCode = 1; }
else console.log('Release output contains no preview fixture marker.');
