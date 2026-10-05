import request from './request.js';

/**
 * 获取交易日历
 */
export function getTradingDaysCalendarApi() {
  return request.get('/api/a-share/calendar/trading-days');
}

/**
 * 标的检索。
 * @param {{q: string, exchange?: string, asset_type?: string, limit?: number}} params
 */
export function searchTickersApi(params) {
  return request.get('/api/meta/tickers/search', params);
}

/**
 * 获取标的列表。
 * 具体筛选和分页参数以 HiThink 文档为准。
 */
export function getTickerListApi(params = {}) {
  return request.get('/api/meta/tickers/list', params);
}

/**
 * 获取行情快照。
 * @param {{thscodes?: string, limit?: number, offset?: number}} params
 */
export function getPriceSnapshotApi(params = {}) {
  return request.get('/api/a-share/prices/snapshot', params);
}

/**
 * 获取单只股票历史日 K。
 * @param {{thscode: string, interval: '1d', start: number, end: number, adjust?: 'none'|'forward'|'backward', offset?: number}} params
 */
export function getHistoricalPriceApi(params) {
  return request.get('/api/a-share/prices/historical', params);
}

/**
 * 获取单只指数历史日 K（无复权参数，时间范围最多 10 年）。
 * @param {{thscode: string, interval: '1d', start: number, end: number}} params
 */
export function getIndexHistoricalPriceApi(params) {
  return request.get('/api/a-share-index/prices/historical', params);
}

/**
 * 特色数据通用接口。
 * resource 示例：hot-stock-list、skyrocket-list、limit-up-pool。
 */
export function getSpecialDataApi(resource, params = {}) {
  return request.get(`/api/a-share/special-data/${resource}`, params);
}

export function getHotStockListApi(period = 'hour') {
  return getSpecialDataApi('hot-stock-list', { period });
}

export function getSkyRocketListApi(period = 'hour') {
  return getSpecialDataApi('skyrocket-list', { period });
}

/**
 * 任意 HiThink 接口的通用调用方式。
 * 示例：hithinkApi({ method: 'get', url: '/api/a-share/calendar/trading-days' })
 */
export function hithinkApi(config) {
  return request.request(config);
}
