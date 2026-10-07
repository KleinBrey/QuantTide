import { useCallback, useEffect, useRef, useState } from 'react';

import { addMarketStockApi, deleteMarketStockApi, getMarketStocksApi } from '@/api/quantide/api.js';
import { moveStock, restoreStockOrder } from '../utils/stockOrder.js';

const MARKET_LABELS = {
  'hk-share': '港股',
  'us-share': '美股'
};

export function useMarketStocks(marketId) {
  const [stocks, setStocks] = useState([]);
  const [selectedStock, setSelectedStock] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mutating, setMutating] = useState(false);
  const [actionError, setActionError] = useState('');
  const requestIdRef = useRef(0);
  const mutationRef = useRef(false);
  const orderKey = `quant-tide:stock-order:${marketId}`;

  const reorderStocks = useCallback(nextStocks => {
    setStocks(nextStocks);
    setActionError('');
    try {
      localStorage.setItem(orderKey, JSON.stringify(nextStocks.map(stock => stock.symbol)));
    } catch {
      setActionError('排序已更新，但浏览器未能保存顺序');
    }
  }, [orderKey]);

  const loadStocks = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');

    try {
      const response = await getMarketStocksApi({ market: marketId });
      if (requestId !== requestIdRef.current) return;

      let nextStocks = Array.isArray(response?.data) ? response.data : [];
      try {
        nextStocks = restoreStockOrder(nextStocks, JSON.parse(localStorage.getItem(orderKey)));
      } catch {
        // 浏览器存储不可用或内容损坏时仍可正常读取股票池。
      }
      setStocks(nextStocks);
      setSelectedStock(current => {
        if (!nextStocks.length) return null;
        return nextStocks.find(stock => stock.symbol === current?.symbol) || nextStocks[0];
      });
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      console.error(`获取${MARKET_LABELS[marketId] || ''}股票池失败`, requestError);
      setError(requestError.message || '获取股票列表失败');
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [marketId, orderKey]);

  const addStock = useCallback(async stock => {
    if (mutationRef.current) return false;
    mutationRef.current = true;
    setMutating(true);
    setActionError('');
    try {
      const response = await addMarketStockApi({ ...stock, market: marketId });
      const added = response.data;
      reorderStocks([added, ...stocks.filter(item => item.symbol !== added.symbol)]);
      setSelectedStock(added);
      setError('');
      return true;
    } finally {
      mutationRef.current = false;
      setMutating(false);
    }
  }, [marketId, reorderStocks, stocks]);

  const removeStock = useCallback(async symbol => {
    if (mutationRef.current) return;
    mutationRef.current = true;
    setMutating(true);
    setActionError('');
    try {
      await deleteMarketStockApi({ market: marketId, symbol });
      const index = stocks.findIndex(stock => stock.symbol === symbol);
      const nextStocks = stocks.filter(stock => stock.symbol !== symbol);
      reorderStocks(nextStocks);
      setSelectedStock(current => current?.symbol === symbol
        ? nextStocks[Math.min(index, nextStocks.length - 1)] || null
        : current);
    } catch (requestError) {
      setActionError(requestError.message || '删除股票失败，请重试');
    } finally {
      mutationRef.current = false;
      setMutating(false);
    }
  }, [marketId, reorderStocks, stocks]);

  const moveStockTo = useCallback((symbol, position) => {
    reorderStocks(moveStock(stocks, symbol, position));
  }, [reorderStocks, stocks]);

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
    mutating,
    actionError,
    addStock,
    removeStock,
    reorderStocks,
    moveStock: moveStockTo,
    refresh: loadStocks
  };
}
