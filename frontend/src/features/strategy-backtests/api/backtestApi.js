import { apiGet } from '@/api/client.js';

export function getBacktestStrategies({ signal } = {}) {
  return apiGet('/api/backtests/strategies', { signal });
}

export function getStrategyBacktest({ strategy, start_date, end_date, max_positions, max_position_pct }, { signal } = {}) {
  const params = new URLSearchParams({ max_positions, max_position_pct: Number(max_position_pct) / 100 });
  if (start_date) params.set('start_date', start_date);
  if (end_date) params.set('end_date', end_date);
  return apiGet(`/api/backtests/${strategy}?${params}`, { signal });
}
