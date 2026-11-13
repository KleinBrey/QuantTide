import { apiGet } from '@/api/client.js';

export function getSignals({ signal } = {}) {
  return apiGet('/api/signals', { signal });
}

export function getSignalResults(signalId, { mode = 'history', startDate, endDate, signal } = {}) {
  const query = new URLSearchParams({ mode });
  if (mode === 'history') {
    if (startDate) query.set('start_date', startDate);
    if (endDate) query.set('end_date', endDate);
  }
  return apiGet(`/api/signals/${encodeURIComponent(signalId)}?${query}`, { signal });
}
