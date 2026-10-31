import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  getWatchlistGroupsApi, getWatchlistItemsApi, createWatchlistGroupApi,
  renameWatchlistGroupApi, deleteWatchlistGroupApi, reorderWatchlistGroupsApi,
  addWatchlistItemApi, deleteWatchlistItemApi, reorderWatchlistItemsApi, syncWatchlistGroupBarsApi
} from '@/api/quantide/api.js';
import { getCryptoSymbols, syncCryptoBars } from '../api/cryptoApi.js';
import { useWatchlistGroupState } from '@/hooks/useWatchlistGroupState.js';

const visibleGroup = group => group.market === 'CRYPTO' || (!group.is_default && !group.market);

export function useCryptoMarket() {
  const { allGroups, setAllGroups, activeGroups, setActiveGroups } = useWatchlistGroupState();
  const [symbols, setSymbols] = useState([]);
  const [selected, setSelected] = useState('');
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [showStockPool, setShowStockPool] = useState(() => localStorage.getItem('quantide:show-crypto-pool') !== 'false');
  const allItems = useRef([]);
  const requestId = useRef(0);
  const busy = useRef(false);
  const activeGroup = useRef(activeGroups.CRYPTO ?? null);
  const groups = allGroups.filter(visibleGroup).filter(group => !group.is_default || showStockPool).sort((a, b) => b.is_default - a.is_default)
    .map(group => group.is_default ? { ...group, name: '交易对池' } : group);
  const groupId = groups.find(group => group.id === activeGroups.CRYPTO)?.id ?? groups[0]?.id ?? null;

  const load = useCallback(async (preferred = '') => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const { data: all } = await getWatchlistGroupsApi();
      const visible = all.filter(visibleGroup).filter(group => !group.is_default || showStockPool).sort((a, b) => b.is_default - a.is_default);
      const active = visible.find(group => group.id === activeGroup.current) || visible[0];
      const items = active ? (await getWatchlistItemsApi(active.id)).data : [];
      if (id !== requestId.current) return;
      activeGroup.current = active?.id ?? null;
      allItems.current = items;
      setAllGroups(all);
      setActiveGroups(current => ({ ...current, CRYPTO: active?.id ?? null }));
      const next = items.filter(item => item.market === 'CRYPTO');
      setSymbols(next);
      setSelected(current => next.find(item => item.symbol === (preferred || current))?.symbol || next[0]?.symbol || '');
    } catch (error) {
      if (id === requestId.current) setError(error.message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [showStockPool, setAllGroups, setActiveGroups]);

  useEffect(() => {
    load();
    return () => { requestId.current += 1; };
  }, [load]);

  async function action(callback, notifyError = false) {
    if (busy.current) return false;
    busy.current = true;
    setSyncing(true);
    setError('');
    try {
      await callback();
      return true;
    } catch (error) {
      if (notifyError) toast.error(error.message || '获取当前分组最新日 K 失败，请重试');
      else setError(error.message);
      return false;
    } finally {
      busy.current = false;
      setSyncing(false);
    }
  }

  async function syncGroup() {
    if (loading || !groupId || !symbols.length) return false;
    const groupName = groups.find(group => group.id === groupId)?.name;
    return action(async () => {
      try {
        const { data } = await syncWatchlistGroupBarsApi(groupId, 'CRYPTO');
        if (data.rows) {
          toast.success(`已更新「${groupName}」${data.symbols} 个资产的最新日 K，共 ${data.rows} 条`);
        } else {
          toast.info(`「${groupName}」暂未获取到可更新的日 K`);
        }
      } finally {
        // 部分交易对失败时也重新读取已经保存的行情。
        setRevision(value => value + 1);
      }
    }, true);
  }

  async function sync(symbol, add = false) {
    return action(async () => {
      // 已有本地行情时，加入分组无需重复请求数据源。
      const known = add && (await getCryptoSymbols()).data.some(item => item.symbol === symbol);
      if (!known) {
        const { data } = await syncCryptoBars(symbol);
        if (!data.rows) throw new Error('该交易对在最近一年暂无行情。');
        toast.success(`已同步 ${symbol} 的 ${data.rows} 条日 K`);
      }
      if (add) {
        await addWatchlistItemApi(activeGroup.current, { market: 'CRYPTO', symbol });
      }
      await load(symbol);
      setRevision(value => value + 1);
    });
  }

  const createGroup = name => action(async () => {
    activeGroup.current = (await createWatchlistGroupApi({ name, market: 'CRYPTO' })).data.id;
    await load();
  });
  const renameGroup = (id, name) => action(async () => { await renameWatchlistGroupApi(id, name); await load(); });
  const deleteGroup = id => action(async () => { await deleteWatchlistGroupApi(id); await load(); });
  const reorderGroups = next => action(async () => {
    let index = 0;
    // 排序只替换当前市场的位置，保留其他市场的分组顺序。
    const merged = allGroups.map(group => visibleGroup(group) && !group.is_default ? next[index++] : group);
    await reorderWatchlistGroupsApi(merged.map(group => group.id));
    await load();
  });
  const addToGroup = (id, symbol) => action(async () => {
    await addWatchlistItemApi(id, { market: 'CRYPTO', symbol });
    await load();
  });
  const removeSymbol = item => action(async () => {
    await deleteWatchlistItemApi(groupId, item.id);
    await load();
  });
  const reorderSymbols = next => action(async () => {
    let index = 0;
    const merged = allItems.current.map(item => item.market === 'CRYPTO' ? next[index++] : item);
    await reorderWatchlistItemsApi(groupId, merged.map(item => item.id));
    await load();
  });

  return {
    symbols, selected, setSelected, loading, syncing, error, revision, sync, syncGroup,
    groups, groupId, createGroup, renameGroup, deleteGroup, reorderGroups, addToGroup, removeSymbol, reorderSymbols,
    hasStockPool: allGroups.some(group => group.market === 'CRYPTO' && group.is_default),
    showStockPool,
    toggleStockPool: visible => {
      localStorage.setItem('quantide:show-crypto-pool', String(visible));
      setShowStockPool(visible);
    },
    selectGroup: id => {
      if (busy.current || loading) return;
      activeGroup.current = id;
      setActiveGroups(current => ({ ...current, CRYPTO: id }));
      setSymbols([]);
      setSelected('');
      setError('');
      load();
    }
  };
}
