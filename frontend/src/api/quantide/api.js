import request from './request.js';

// 获取股票标的列表
export function getStocksListApi(params = {}) {
  return request.get('/api/stocks-list', params);
}

// 获取港股或美股数据库中的股票池
export function getMarketStocksApi(params = {}) {
  return request.get('/api/market-stocks', params);
}

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
