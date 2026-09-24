import { apiGet } from '@/api/client.js';

export function getSignals({ signal } = {}) {
  return apiGet('/api/signals', { signal });
}

export function getSignalResults(signalId, { limit = 100, signal } = {}) {
  return apiGet(`/api/signals/${encodeURIComponent(signalId)}?limit=${limit}`, { signal });
}
