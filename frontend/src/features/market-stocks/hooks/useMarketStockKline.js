import { useEffect, useRef, useState } from 'react';
import moment from 'moment';

import { getDailyBarsApi } from '@/api/quantide/api.js';

const historyCache = new Map();
const marketCacheVersions = new Map();

export function invalidateMarketStockKlines(marketId) {
  marketCacheVersions.set(marketId, (marketCacheVersions.get(marketId) || 0) + 1);
  for (const key of historyCache.keys()) {
    if (key.startsWith(`${marketId}:`)) historyCache.delete(key);
  }
}

function transformHistory(items) {
  if (!Array.isArray(items)) return [];

  return items.map(item => ({
    date: item.trade_date,
    open: Number(item.open),
    high: Number(item.high),
    low: Number(item.low),
    close: Number(item.close),
    volume: Number(item.volume)
  }));
}

export function useMarketStockKline(marketId, symbol, revision = 0) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;

    if (!symbol) {
      setData(null);
      setLoading(false);
      setError('');
      return undefined;
    }

    const cacheKey = `${marketId}:${symbol}`;
    const cacheVersion = marketCacheVersions.get(marketId) || 0;
    const cachedRows = historyCache.get(cacheKey);
    if (cachedRows) {
      setData({ rows: cachedRows });
      setLoading(false);
      setError('');
      return undefined;
    }

    setData(null);
    setLoading(true);
    setError('');

    getDailyBarsApi({
      market: marketId,
      symbol,
      start: moment().subtract(1, 'year').format('YYYY-MM-DD'),
      end: moment().format('YYYY-MM-DD')
    })
      .then(response => {
        if (requestId !== requestIdRef.current || cacheVersion !== (marketCacheVersions.get(marketId) || 0)) return;
        const rows = transformHistory(response?.data);
        historyCache.set(cacheKey, rows);
        setData({ rows });
      })
      .catch(requestError => {
        if (requestId !== requestIdRef.current) return;
        console.error('K 线加载失败', requestError);
        setData(null);
        setError(requestError.message || 'K 线加载失败');
      })
      .finally(() => {
        if (requestId === requestIdRef.current) setLoading(false);
      });

    return () => {
      requestIdRef.current += 1;
    };
  }, [marketId, symbol, revision]);

  return { data, loading, error };
}
