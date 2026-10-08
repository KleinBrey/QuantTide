import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  addMarketStockApi,
  getWatchlistGroupsApi,
  getWatchlistItemsApi,
  reorderWatchlistItemsApi,
  createWatchlistGroupApi,
  renameWatchlistGroupApi,
  deleteWatchlistGroupApi,
  reorderWatchlistGroupsApi,
  addWatchlistItemApi,
  deleteWatchlistItemApi
} from '@/api/quantide/api.js';
import { moveStock } from '../utils/stockOrder.js';

// 分市场展示时保留跨市场分组中其他市场成员/分组的相对位置。
function mergeVisibleOrder(all, visible, isVisible) {
  let index = 0;
  return all.map(row => (isVisible(row) ? visible[index++] : row));
}

function isVisibleGroup(group, market) {
  return !group.is_default && (!group.market || group.market === market);
}

export function useMarketStocks(marketId) {
  const market = { 'a-share': 'CN', 'hk-share': 'HK', 'us-share': 'US' }[marketId];
  const [allGroups, setAllGroups] = useState([]);
  const [activeGroups, setActiveGroups] = useState({});
  const groups = useMemo(() => allGroups.filter(group => isVisibleGroup(group, market)), [allGroups, market]);
  const groupId = groups.find(group => group.id === activeGroups[market])?.id ?? groups[0]?.id ?? null;
  const [stocks, setStocks] = useState([]);
  const [stocksMarket, setStocksMarket] = useState(null);
  const [selectedStock, setSelectedStock] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mutating, setMutating] = useState(false);
  const [actionError, setActionError] = useState('');
  const requestRef = useRef(0);
  const activeMarketRef = useRef(market);
  const mutationRef = useRef(false);
  const activeGroupsRef = useRef({});
  const allGroupsRef = useRef([]);
  const allItemsRef = useRef([]);

  const loadStocks = useCallback(
    async preferred => {
      // 切换后，旧市场尚未完成的操作不能重新发起请求覆盖当前市场。
      if (activeMarketRef.current !== market) return;
      const requestId = ++requestRef.current;
      setLoading(true);
      setError('');
      try {
        const allGroups = (await getWatchlistGroupsApi()).data;
        const visibleGroups = allGroups.filter(group => isVisibleGroup(group, market));
        const active = visibleGroups.find(group => group.id === activeGroupsRef.current[market]) || visibleGroups[0];
        const allItems = active ? (await getWatchlistItemsApi(active.id)).data : [];
        if (requestId !== requestRef.current) return;
        allGroupsRef.current = allGroups;
        allItemsRef.current = allItems;
        activeGroupsRef.current[market] = active?.id ?? null;
        setActiveGroups(current => ({ ...current, [market]: active?.id ?? null }));
        setAllGroups(allGroups);
        const next = allItems.filter(item => item.market === market);
        setStocks(next);
        setStocksMarket(market);
        setSelectedStock(
          current => next.find(stock => stock.symbol === (preferred || current?.symbol)) || next[0] || null
        );
      } catch (requestError) {
        if (requestId === requestRef.current) {
          setStocks([]);
          setStocksMarket(market);
          setSelectedStock(null);
          setError(requestError.message || '获取股票列表失败');
        }
      } finally {
        if (requestId === requestRef.current) setLoading(false);
      }
    },
    [market]
  );

  const mutate = useCallback(async action => {
    if (mutationRef.current) return false;
    mutationRef.current = true;
    setMutating(true);
    setActionError('');
    try {
      await action();
      return true;
    } finally {
      mutationRef.current = false;
      setMutating(false);
    }
  }, []);

  const runAction = useCallback(
    async action => {
      try {
        return await mutate(action);
      } catch (requestError) {
        await loadStocks();
        if (activeMarketRef.current === market) setActionError(requestError.message || '操作失败，请重试');
        return false;
      }
    },
    [mutate, loadStocks, market]
  );

  const selectGroup = id => {
    if (mutationRef.current || loading || stocksMarket !== market || id === activeGroupsRef.current[market]) return;
    activeGroupsRef.current[market] = id;
    setStocks([]);
    setSelectedStock(null);
    setActiveGroups(current => ({ ...current, [market]: id }));
    setActionError('');
    loadStocks();
  };

  const addStock = useCallback(
    stock =>
      mutate(async () => {
        const active = allGroupsRef.current.find(group => group.id === activeGroupsRef.current[market]);
        let symbol = stock.symbol;
        if (active.is_default) {
          symbol = (await addMarketStockApi({ ...stock, market: marketId })).data.symbol;
        } else {
          try {
            symbol = (await addWatchlistItemApi(active.id, { market, symbol })).data.symbol;
          } catch (requestError) {
            if (market === 'CN') {
              if (requestError.response?.data?.detail === '股票基础信息不存在，请先添加到对应市场股票池') {
                throw new Error('未找到该 A 股，请先在数据同步中更新股票列表');
              }
              throw requestError;
            }
            if (requestError.response?.data?.detail !== '股票基础信息不存在，请先添加到对应市场股票池')
              throw requestError;
            symbol = (await addMarketStockApi({ ...stock, market: marketId })).data.symbol;
            await addWatchlistItemApi(active.id, { market, symbol });
          }
        }
        await loadStocks(symbol);
      }),
    [marketId, market, mutate, loadStocks]
  );

  const removeStock = symbol =>
    runAction(async () => {
      const item = stocks.find(stock => stock.symbol === symbol);
      await deleteWatchlistItemApi(activeGroupsRef.current[market], item.id);
      await loadStocks();
    });

  const reorderStocks = next =>
    runAction(async () => {
      const merged = mergeVisibleOrder(allItemsRef.current, next, item => item.market === market);
      await reorderWatchlistItemsApi(
        activeGroupsRef.current[market],
        merged.map(item => item.id)
      );
      if (activeMarketRef.current !== market) return;
      allItemsRef.current = merged;
      setStocks(next);
    });

  const reorderGroups = next =>
    runAction(async () => {
      const merged = mergeVisibleOrder(allGroupsRef.current, next, group => isVisibleGroup(group, market));
      await reorderWatchlistGroupsApi(merged.map(group => group.id));
      if (activeMarketRef.current !== market) return;
      allGroupsRef.current = merged;
      setAllGroups(merged);
    });

  const createGroup = name =>
    runAction(async () => {
      const created = (await createWatchlistGroupApi({ name, market })).data;
      activeGroupsRef.current[market] = created.id;
      await loadStocks();
    });

  const renameGroup = (id, name) =>
    runAction(async () => {
      await renameWatchlistGroupApi(id, name);
      await loadStocks();
    });

  const deleteGroup = id =>
    runAction(async () => {
      await deleteWatchlistGroupApi(id);
      await loadStocks();
    });

  const addToGroup = (id, stock) =>
    runAction(async () => {
      await addWatchlistItemApi(id, { market, symbol: stock.symbol });
      await loadStocks();
    });

  useEffect(() => {
    activeMarketRef.current = market;
    loadStocks();
    return () => {
      activeMarketRef.current = null;
      requestRef.current += 1;
    };
  }, [loadStocks, market]);

  return {
    // 新市场完成加载前隐藏旧市场数据，分组栏继续使用已读取的共享分组。
    stocks: stocksMarket === market ? stocks : [],
    selectedStock: stocksMarket === market ? selectedStock : null,
    setSelectedStock,
    loading: loading || stocksMarket !== market,
    error: stocksMarket === market ? error : '',
    mutating,
    actionError: stocksMarket === market ? actionError : '',
    groups,
    groupId,
    selectGroup,
    createGroup,
    renameGroup,
    deleteGroup,
    reorderGroups,
    addToGroup,
    addStock,
    removeStock,
    reorderStocks,
    moveStock: (symbol, position) => reorderStocks(moveStock(stocks, symbol, position)),
    refresh: () => loadStocks()
  };
}
