import { useCallback, useEffect, useRef, useState } from 'react';

import { getHKHotStocksApi, getHotStocksApi, getUSHotStocksApi } from '../api/hotRankingsApi.js';
import { transformHotRankingResponse } from '../utils/transformers.js';

const MARKET_CONFIG = {
  'a-share': {
    title: 'A股热榜',
    request: getHotStocksApi
  },
  'hk-share': {
    title: '港股热榜',
    request: getHKHotStocksApi
  },
  'us-share': {
    title: '美股热榜',
    request: getUSHotStocksApi
  }
};

export function useHotStockRanking(marketId = 'a-share') {
  const market = MARKET_CONFIG[marketId] ?? MARKET_CONFIG['a-share'];

  // 分别保存热榜数据、加载状态和请求错误。
  const [ranking, setRanking] = useState({
    title: market.title,
    timestamp: null,
    rows: []
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 记录最新请求的编号，防止较早发出的请求覆盖较新的请求结果。
  const requestIdRef = useRef(0);

  // useCallback 保持函数引用稳定，使下面的 useEffect 不会因函数引用变化而重复执行。
  const loadRanking = useCallback(async () => {
    // 每次发起请求都生成一个新的编号；编号最大的请求代表当前最新请求。
    const requestId = ++requestIdRef.current;
    // 重置 loading 和 error 状态
    setLoading(true);
    setError('');

    try {
      const response = await market.request();

      // 过期请求直接忽略
      if (requestId !== requestIdRef.current) return;

      const nextRanking = transformHotRankingResponse(response?.data);
      setRanking({
        ...nextRanking,
        title: market.title
      });
    } catch (requestError) {
      // 过期请求直接忽略
      if (requestId !== requestIdRef.current) return;
      console.error(`获取${market.title}失败`, requestError);
      setError(requestError.message || `获取${market.title}失败`);
    } finally {
      // 过期请求直接忽略
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [market]);

  useEffect(() => {
    // Hook 首次挂载时自动加载热榜。
    loadRanking();

    // 卸载时让尚未完成的请求失效，避免请求返回后继续更新状态。
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadRanking]);

  // refresh 供页面上的刷新操作使用，本质上就是重新执行 loadRanking。
  return {
    ranking,
    loading,
    error,
    refresh: loadRanking
  };
}
