import request from './request.js';

// 获取股票标的列表
export function getStocksListApi(params = {}) {
  return request.get('/api/stocks-list', params);
}

// 获取港股或美股数据库中的股票池
export function getMarketStocksApi(params = {}) {
  return request.get('/api/market-stocks', params);
}

export function addMarketStockApi(stock) {
  return request.post('/api/market-stocks', stock);
}

export function deleteMarketStockApi(params) {
  return request.delete('/api/market-stocks', params);
}

export const getWatchlistGroupsApi = () => request.get('/api/watchlists/groups');
export const createWatchlistGroupApi = body => request.post('/api/watchlists/groups', body);
export const renameWatchlistGroupApi = (id, name) => request.patch(`/api/watchlists/groups/${id}`, { name });
export const deleteWatchlistGroupApi = id => request.delete(`/api/watchlists/groups/${id}`);
export const reorderWatchlistGroupsApi = ids => request.put('/api/watchlists/groups/order', { ids });
export const getWatchlistItemsApi = id => request.get(`/api/watchlists/groups/${id}/items`);
export const addWatchlistItemApi = (id, stock) => request.post(`/api/watchlists/groups/${id}/items`, stock);
export const deleteWatchlistItemApi = (groupId, itemId) => request.delete(`/api/watchlists/groups/${groupId}/items/${itemId}`);
export const reorderWatchlistItemsApi = (id, ids) => request.put(`/api/watchlists/groups/${id}/items/order`, { ids });
export const searchWatchlistStocksApi = params => request.get('/api/watchlists/stocks/search', params);

// 更新股票标的列表
export function updateStocksListApi(params = {}) {
  return request.post('/api/stocks-list', params);
}

// 获取指定股票在日期范围内的日 K 线
export function getDailyBarsApi(params = {}) {
  return request.get('/api/daily-bars', params);
}

// 获取最新 A 股热度榜
export function getHotStocksApi(params = {}) {
  return request.get('/api/hot-stock', params);
}

// 获取最新港股热度榜
export function getHKHotStocksApi(params = {}) {
  return request.get('/api/hk-hot-stock', params);
}

// 获取最新美股热度榜
export function getUSHotStocksApi(params = {}) {
  return request.get('/api/us-hot-stock', params);
}
