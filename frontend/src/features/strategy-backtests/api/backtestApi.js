import { apiGet } from '@/api/client.js';

export function getConfirmedVolumeBreakoutBacktest({ signal } = {}) {
  return apiGet('/api/backtests/confirmed_volume_breakout', { signal });
}
