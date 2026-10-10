import request from '@/api/quantide/request.js';

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
