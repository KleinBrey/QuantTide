import request from './request.js';

// 前端使用统一市场命名；请求边界转换为后端现有的协议值。
const API_MARKETS = {
  cn_stock: 'a-share',
  hk_stock: 'hk-share',
  us_stock: 'us-share'
};

function withApiMarket(params) {
  if (!params.market) return params;
  return { ...params, market: API_MARKETS[params.market] ?? params.market };
}

// 获取股票标的列表
export function getStocksListApi(params = {}) {
  return request.get('/api/stocks-list', params);
}

// 获取港股或美股数据库中的股票池
export function getMarketStocksApi(params = {}) {
  return request.get('/api/market-stocks', withApiMarket(params));
}

export function addMarketStockApi(stock) {
  return request.post('/api/market-stocks', withApiMarket(stock));
}

export function deleteMarketStockApi(params) {
  return request.delete('/api/market-stocks', withApiMarket(params));
}

export const resetFuturesPoolApi = () => request.post('/api/watchlists/futures-pool/reset');

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
  return request.get('/api/daily-bars', withApiMarket(params));
}
