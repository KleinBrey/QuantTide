import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  addMarketStockApi,
  resetFuturesPoolApi,
  getWatchlistGroupsApi,
  getWatchlistItemsApi,
  syncWatchlistGroupBarsApi,
  reorderWatchlistItemsApi,
  createWatchlistGroupApi,
  renameWatchlistGroupApi,
  deleteWatchlistGroupApi,
  reorderWatchlistGroupsApi,
  addWatchlistItemApi,
  deleteWatchlistItemApi
} from '@/api/quantide/api.js';
import { moveStock } from '../utils/stockOrder.js';
import { useWatchlistGroupState } from '@/hooks/useWatchlistGroupState.js';
import { invalidateMarketStockKlines } from './useMarketStockKline.js';

// 分市场展示时保留跨市场分组中其他市场成员/分组的相对位置。
function mergeVisibleOrder(all, visible, isVisible) {
  let index = 0;
  return all.map(row => (isVisible(row) ? visible[index++] : row));
}

function isVisibleGroup(group, market) {
  return !group.is_default && (!group.market || group.market === market);
}

const STOCK_POOL_VISIBILITY_KEY = 'quantide:show-stock-pool';

function visibleGroups(allGroups, market, showStockPool) {
  const customGroups = allGroups.filter(group => isVisibleGroup(group, market));
  const pool = (showStockPool || market === 'FUTURES') && allGroups.find(group => group.is_default && group.market === market);
  return pool ? [{ ...pool, name: market === 'FUTURES' ? '主力合约' : '股票池' }, ...customGroups] : customGroups;
}

export function useMarketStocks(marketId) {
  const market = { 'cn_stock': 'CN', 'hk_stock': 'HK', 'us_stock': 'US', futures: 'FUTURES' }[marketId];
  const { allGroups, setAllGroups, activeGroups, setActiveGroups } = useWatchlistGroupState();
  const [showStockPool, setShowStockPool] = useState(() => {
    try {
      return window.localStorage.getItem(STOCK_POOL_VISIBILITY_KEY) === 'true';
    } catch {
      return false;
    }
  });
  const groups = useMemo(() => visibleGroups(allGroups, market, showStockPool), [allGroups, market, showStockPool]);
  const hasStockPool = allGroups.some(group => group.is_default && group.market === market);
  const groupId = groups.find(group => group.id === activeGroups[market])?.id ?? groups[0]?.id ?? null;
  const [stocks, setStocks] = useState([]);
  const [stocksMarket, setStocksMarket] = useState(null);
  const [selectedStock, setSelectedStock] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [mutating, setMutating] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [revision, setRevision] = useState(0);
  const [actionError, setActionError] = useState('');
  const requestRef = useRef(0);
  const activeMarketRef = useRef(market);
  const mutationRef = useRef(false);
  const activeGroupsRef = useRef(activeGroups);
  const allGroupsRef = useRef(allGroups);
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
        const availableGroups = visibleGroups(allGroups, market, showStockPool);
        const active =
          availableGroups.find(group => group.id === activeGroupsRef.current[market]) || availableGroups[0];
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
    [market, showStockPool, setAllGroups, setActiveGroups]
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

  const syncGroup = async () => {
    if (loading || stocksMarket !== market || !groupId || !stocks.length) return false;
    const groupName = groups.find(group => group.id === groupId)?.name;
    return mutate(async () => {
      setSyncing(true);
      try {
        const { data } = await syncWatchlistGroupBarsApi(groupId, market);
        if (data.rows) {
          toast.success(`已更新「${groupName}」${data.symbols} 个资产的最新日 K，共 ${data.rows} 条`);
        } else {
          toast.info(`「${groupName}」暂未获取到可更新的日 K`);
        }
      } catch (requestError) {
        toast.error(requestError.message || '获取当前分组最新日 K 失败，请重试');
      } finally {
        // 部分失败时也刷新已保存的行情，同时清除组内其他资产的旧缓存。
        invalidateMarketStockKlines(marketId);
        if (activeMarketRef.current === market) setRevision(value => value + 1);
        setSyncing(false);
      }
    });
  };

  const selectGroup = id => {
    if (mutationRef.current || loading || stocksMarket !== market || id === activeGroupsRef.current[market]) return;
    activeGroupsRef.current[market] = id;
    setStocks([]);
    setSelectedStock(null);
    setActiveGroups(current => ({ ...current, [market]: id }));
    setActionError('');
    loadStocks();
  };

  const toggleStockPool = visible => {
    if (mutationRef.current || loading || visible === showStockPool) return;
    setStocks([]);
    setSelectedStock(null);
    setLoading(true);
    setActionError('');
    setShowStockPool(visible);
    try {
      window.localStorage.setItem(STOCK_POOL_VISIBILITY_KEY, String(visible));
    } catch {
      // 存储不可用时，开关仍在当前页面生效。
    }
  };

  const addStock = useCallback(
    stock =>
      mutate(async () => {
        const active = allGroupsRef.current.find(group => group.id === activeGroupsRef.current[market]);
        let symbol = stock.symbol;
        if (market === 'FUTURES') {
          // 日线任务读取默认池；加入自选分组的合约也需要进入同步范围。
          const pool = allGroupsRef.current.find(group => group.is_default && group.market === market);
          const poolItems = (await getWatchlistItemsApi(pool.id)).data;
          if (!poolItems.some(item => item.symbol === symbol)) {
            await addWatchlistItemApi(pool.id, { market, symbol });
          }
          if (active.id !== pool.id) await addWatchlistItemApi(active.id, { market, symbol });
        } else if (active.is_default) {
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
      const sortableGroups = next.filter(group => isVisibleGroup(group, market));
      const merged = mergeVisibleOrder(allGroupsRef.current, sortableGroups, group => isVisibleGroup(group, market));
      await reorderWatchlistGroupsApi(merged.map(group => group.id));
      if (activeMarketRef.current !== market) return;
      allGroupsRef.current = merged;
      setAllGroups(merged);
    });

  const resetFuturesPool = () =>
    runAction(async () => {
      const { group_id: poolId } = (await resetFuturesPoolApi()).data;
      if (activeMarketRef.current !== market) return;
      activeGroupsRef.current[market] = poolId;
      setActiveGroups(current => ({ ...current, [market]: poolId }));
      await loadStocks();
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
    syncing,
    revision,
    syncGroup,
    actionError: stocksMarket === market ? actionError : '',
    groups,
    hasStockPool,
    showStockPool,
    toggleStockPool,
    groupId,
    selectGroup,
    resetFuturesPool,
    createGroup,
    renameGroup,
    deleteGroup,
    reorderGroups,
    addToGroup,
    addStock,
    removeStock,
    reorderStocks,
    moveStock: (symbol, position) => reorderStocks(moveStock(stocks, symbol, position))
  };
}
