import { useCallback, useEffect, useRef, useState } from 'react';
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
  const [groups, setGroups] = useState([]);
  const [groupId, setGroupId] = useState(null);
  const [stocks, setStocks] = useState([]);
  const [selectedStock, setSelectedStock] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mutating, setMutating] = useState(false);
  const [actionError, setActionError] = useState('');
  const requestRef = useRef(0);
  const mutationRef = useRef(false);
  const activeGroupRef = useRef(null);
  const allGroupsRef = useRef([]);
  const allItemsRef = useRef([]);

  const loadStocks = useCallback(
    async preferred => {
      const requestId = ++requestRef.current;
      setLoading(true);
      setError('');
      try {
        const allGroups = (await getWatchlistGroupsApi()).data;
        const visibleGroups = allGroups.filter(group => isVisibleGroup(group, market));
        const active = visibleGroups.find(group => group.id === activeGroupRef.current) || visibleGroups[0];
        const allItems = active ? (await getWatchlistItemsApi(active.id)).data : [];
        if (requestId !== requestRef.current) return;
        allGroupsRef.current = allGroups;
        allItemsRef.current = allItems;
        activeGroupRef.current = active?.id ?? null;
        setGroupId(active?.id ?? null);
        setGroups(visibleGroups);
        const next = allItems.filter(item => item.market === market);
        setStocks(next);
        setSelectedStock(
          current => next.find(stock => stock.symbol === (preferred || current?.symbol)) || next[0] || null
        );
      } catch (requestError) {
        if (requestId === requestRef.current) {
          setStocks([]);
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
        setActionError(requestError.message || '操作失败，请重试');
        return false;
      }
    },
    [mutate, loadStocks]
  );

  const selectGroup = id => {
    if (mutationRef.current || loading || id === activeGroupRef.current) return;
    activeGroupRef.current = id;
    setStocks([]);
    setSelectedStock(null);
    setGroupId(id);
    setActionError('');
    loadStocks();
  };

  const addStock = useCallback(
    stock =>
      mutate(async () => {
        const active = allGroupsRef.current.find(group => group.id === activeGroupRef.current);
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
      await deleteWatchlistItemApi(activeGroupRef.current, item.id);
      await loadStocks();
    });

  const reorderStocks = next =>
    runAction(async () => {
      const merged = mergeVisibleOrder(allItemsRef.current, next, item => item.market === market);
      await reorderWatchlistItemsApi(
        activeGroupRef.current,
        merged.map(item => item.id)
      );
      allItemsRef.current = merged;
      setStocks(next);
    });

  const reorderGroups = next =>
    runAction(async () => {
      const merged = mergeVisibleOrder(allGroupsRef.current, next, group => isVisibleGroup(group, market));
      await reorderWatchlistGroupsApi(merged.map(group => group.id));
      allGroupsRef.current = merged;
      setGroups(next);
    });

  const createGroup = name =>
    runAction(async () => {
      const created = (await createWatchlistGroupApi({ name, market })).data;
      activeGroupRef.current = created.id;
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
    activeGroupRef.current = null;
    loadStocks();
    return () => {
      requestRef.current += 1;
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
