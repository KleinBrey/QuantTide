import { useCallback, useEffect, useRef, useState } from 'react';
import { addMarketStockApi, getMarketStocksApi } from '@/api/quantide/api.js';
import { stockPoolSymbol } from '../utils/stockPool.js';

export function useStockPool(marketId, rows) {
  const enabled = marketId === 'hk-share' || marketId === 'us-share';
  const [symbols, setSymbols] = useState(new Set());
  const [pending, setPending] = useState(new Set());
  const [ready, setReady] = useState(false);
  const stateRef = useRef(null);

  const refresh = useCallback(async () => {
    const state = stateRef.current;
    if (!enabled || !state || state.pending.size) return;
    const requestId = ++state.requestId;
    state.ready = false;
    setReady(false);
    try {
      const response = await getMarketStocksApi({ market: marketId });
      if (stateRef.current !== state || state.requestId !== requestId) return;
      state.symbols = new Set(response.data.map(stock => stockPoolSymbol(stock, marketId)));
      state.ready = true;
      setReady(true);
      setSymbols(state.symbols);
    } catch (requestError) {
      if (stateRef.current === state && state.requestId === requestId) {
        console.error('获取 stock_pool 失败', requestError);
      }
    }
  }, [enabled, marketId]);

  const addStock = useCallback(async stock => {
    const state = stateRef.current;
    const symbol = stockPoolSymbol(stock, marketId);
    // 已加入、尚未读取池状态或正在添加时，点击均不发起写入。
    if (!enabled || !state?.ready || !symbol || state.symbols.has(symbol) || state.pending.has(symbol)) return;
    state.pending.add(symbol);
    setPending(new Set(state.pending));
    try {
      try {
        await addMarketStockApi({ market: marketId, symbol, name: stock.name });
      } catch (requestError) {
        // 其他页面已加入同一股票时，以 SQLite 的实际成员为准。
        if (requestError.response?.status !== 409) throw requestError;
        const response = await getMarketStocksApi({ market: marketId });
        if (!response.data.some(item => stockPoolSymbol(item, marketId) === symbol)) throw requestError;
      }
      if (stateRef.current !== state) return;
      state.symbols = new Set([...state.symbols, symbol]);
      setSymbols(state.symbols);
    } catch (requestError) {
      if (stateRef.current === state) console.error('加入 stock_pool 失败', requestError);
    } finally {
      state.pending.delete(symbol);
      if (stateRef.current === state) setPending(new Set(state.pending));
    }
  }, [enabled, marketId]);

  useEffect(() => {
    const state = { symbols: new Set(), pending: new Set(), ready: false, requestId: 0 };
    stateRef.current = state;
    setSymbols(state.symbols);
    setPending(new Set());
    setReady(false);
    return () => { stateRef.current = null; };
  }, [enabled, marketId]);

  useEffect(() => {
    refresh();
  }, [refresh, rows]);

  return { enabled, symbols, pending, ready, addStock };
}
