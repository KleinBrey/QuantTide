import { useCallback, useEffect, useRef, useState } from 'react';

import { getMarketStocksApi } from '@/api/quantide/api.js';

const MARKET_LABELS = {
  'hk-share': '港股',
  'us-share': '美股'
};

export function useMarketStocks(marketId) {
  const [stocks, setStocks] = useState([]);
  const [selectedStock, setSelectedStock] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  const loadStocks = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');

    try {
      const response = await getMarketStocksApi({ market: marketId });
      if (requestId !== requestIdRef.current) return;

      const nextStocks = Array.isArray(response?.data) ? response.data : [];
      setStocks(nextStocks);
      setSelectedStock(current => {
        if (!nextStocks.length) return null;
        return nextStocks.find(stock => stock.symbol === current?.symbol) || nextStocks[0];
      });
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      console.error(`获取${MARKET_LABELS[marketId] || ''}股票池失败`, requestError);
      setStocks([]);
      setSelectedStock(null);
      setError(requestError.message || '获取股票列表失败');
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [marketId]);

  useEffect(() => {
    loadStocks();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadStocks]);

  return {
    stocks,
    selectedStock,
    setSelectedStock,
    loading,
    error,
    refresh: loadStocks
  };
}
