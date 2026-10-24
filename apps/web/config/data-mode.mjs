/** One app-wide data source. Never combine live and preview adapters. */
export function resolveDataMode(value = 'live', production = false) {
  if (value !== 'live' && value !== 'mock') throw new Error('NEXT_PUBLIC_DATA_MODE must be live or mock');
  if (production && value !== 'live') throw new Error('Mock data is forbidden in production. Set NEXT_PUBLIC_DATA_MODE=live.');
  return value;
}
export function assertDataSource(mode, source, production = false) {
  if (mode !== source || production && source !== 'live') throw new Error('Data adapter does not match the configured mode');
}
