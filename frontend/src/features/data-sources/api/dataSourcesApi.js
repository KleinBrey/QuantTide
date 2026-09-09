import request from '@/api/quantide/request.js';

export function fetchLatestUpdateTimes() {
  return request.get('/api/database-sync/latest-update-times');
}

export function syncStockList() {
  return request.post('/api/database-sync/stock-list', {}, { timeout: 0 });
}

export function syncDailyK() {
  return request.post('/api/database-sync/daily-k', {}, { timeout: 0 });
}

export function syncStockDailyBasic() {
  return request.post('/api/database-sync/stock-daily-basic', {}, { timeout: 0 });
}

export function syncHotStock() {
  return request.post('/api/database-sync/hot-stock', {}, { timeout: 0 });
}
