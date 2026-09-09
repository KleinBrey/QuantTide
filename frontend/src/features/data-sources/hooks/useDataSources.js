import { useCallback, useEffect, useRef, useState } from 'react';

import {
  fetchLatestUpdateTimes,
  syncDailyK,
  syncHotStock,
  syncStockDailyBasic,
  syncStockList
} from '../api/dataSourcesApi.js';

const SYNC_TASKS = [
  {
    id: 'hot-stock',
    name: '股票热度',
    description: '获取当天 A 股、港股和美股热度榜，并更新对应数据表。',
    run: syncHotStock
  },
  {
    id: 'daily-k',
    name: '日 K 线数据',
    description: '同步最近 3 个自然日的行情，每批处理 100 只股票。',
    run: syncDailyK
  },
  {
    id: 'stock-daily-basic',
    name: '股票每日指标',
    description: '获取最新交易日全部 A 股总市值，并更新股票每日指标表。',
    run: syncStockDailyBasic
  },
  {
    id: 'stock-list',
    name: 'A 股股票列表',
    description: '拉取并写入最新 A 股基础信息，建议先执行这个任务。',
    run: syncStockList
  }
];

const INITIAL_RESULTS = Object.fromEntries(
  SYNC_TASKS.map(task => [task.id, { status: 'idle', message: '', finishedAt: '', duration: null }])
);

export function useDataSources() {
  const [results, setResults] = useState(INITIAL_RESULTS);
  const [latestUpdateTimes, setLatestUpdateTimes] = useState({});
  const [latestDataStatus, setLatestDataStatus] = useState('loading');
  const [error, setError] = useState('');
  const activeTask = useRef(null);
  const latestRequestId = useRef(0);

  const loadLatestUpdateTimes = useCallback(async () => {
    const requestId = latestRequestId.current + 1;
    latestRequestId.current = requestId;
    setLatestDataStatus('loading');

    try {
      const { data } = await fetchLatestUpdateTimes();
      if (requestId !== latestRequestId.current) return;
      setLatestUpdateTimes(data);
      setLatestDataStatus('ready');
    } catch {
      if (requestId !== latestRequestId.current) return;
      setLatestDataStatus('failed');
    }
  }, []);

  useEffect(() => {
    void loadLatestUpdateTimes();
  }, [loadLatestUpdateTimes]);

  const runSync = useCallback(
    async taskId => {
      if (activeTask.current) return;

      const task = SYNC_TASKS.find(item => item.id === taskId);
      if (!task) return;

      activeTask.current = taskId;
      setError('');
      setResults(current => ({
        ...current,
        [taskId]: { status: 'running', message: '正在执行同步脚本…', finishedAt: '', duration: null }
      }));

      try {
        const { data } = await task.run();
        setResults(current => ({
          ...current,
          [taskId]: {
            status: 'success',
            message: data.message,
            finishedAt: data.finished_at,
            duration: data.duration_seconds
          }
        }));
        void loadLatestUpdateTimes();
      } catch (requestError) {
        const message = requestError.response?.data?.detail || requestError.message || '同步脚本执行失败';
        setError(`${task.name}：${message}`);
        setResults(current => ({
          ...current,
          [taskId]: { status: 'failed', message: '同步脚本执行失败', finishedAt: '', duration: null }
        }));
      } finally {
        activeTask.current = null;
      }
    },
    [loadLatestUpdateTimes]
  );

  const runningTaskId = Object.keys(results).find(taskId => results[taskId].status === 'running') || null;

  return {
    tasks: SYNC_TASKS,
    results,
    latestUpdateTimes,
    latestDataStatus,
    runningTaskId,
    error,
    runSync
  };
}
