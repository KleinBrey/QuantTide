import { useCallback, useEffect, useRef, useState } from 'react';

import {
  fetchTasks, fetchScripts, fetchLatestUpdateTimes, createTask, updateTask,
  deleteTask, setTaskEnabled, reorderTasks as persistTaskOrder, runTask as executeTask
} from '../api/dataSourcesApi.js';

export function useDataSources() {
  const [tasks, setTasks] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [settings, setSettings] = useState({ timezone: 'Asia/Shanghai', scheduler_enabled: true });
  const [latestUpdateTimes, setLatestUpdateTimes] = useState({});
  const [latestDataStatus, setLatestDataStatus] = useState('loading');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pendingTaskId, setPendingTaskId] = useState(null);
  const [reordering, setReordering] = useState(false);
  const activeTask = useRef(null);
  const reorderInFlight = useRef(false);
  const requestId = useRef(0);

  const loadTasks = useCallback(async () => {
    if (reorderInFlight.current) return;
    // 多次查询重叠时，只采用最近一次请求的结果。
    const currentId = ++requestId.current;
    const { data } = await fetchTasks();
    if (currentId === requestId.current && !reorderInFlight.current) setTasks(data);
  }, []);

  const loadLatestUpdateTimes = useCallback(async () => {
    try {
      const { data } = await fetchLatestUpdateTimes();
      setLatestUpdateTimes(data);
      setLatestDataStatus('ready');
    } catch {
      setLatestDataStatus('failed');
    }
  }, []);

  const reload = useCallback(async () => {
    if (reorderInFlight.current) return;
    setLoading(true);
    setError('');
    try {
      await loadTasks();
      const { data } = await fetchScripts();
      setScripts(data.scripts);
      setSettings({ timezone: data.timezone, scheduler_enabled: data.scheduler_enabled });
      await loadLatestUpdateTimes();
    } catch (err) {
      setError(err.message || '任务列表读取失败');
    } finally {
      setLoading(false);
    }
  }, [loadTasks, loadLatestUpdateTimes]);

  useEffect(() => {
    // 进入页面加载一次，后续由用户点击“刷新”查询。
    void reload();
  }, [reload]);

  const saveTask = async (id, data) => {
    setError('');
    let response;
    if (id) {
      response = await updateTask(id, data);
    } else {
      response = await createTask(data);
    }
    const saved = response.data;
    // 操作成功后直接使用响应更新页面，不额外查询列表。
    ++requestId.current;
    setTasks(current => {
      if (id) return current.map(task => task.id === id ? { ...task, ...saved, sort_order: task.sort_order, next_run_at: null } : task);
      return [...current, saved];
    });
  };

  const removeTask = async id => {
    setError('');
    await deleteTask(id);
    ++requestId.current;
    setTasks(current => current.filter(task => task.id !== id));
  };

  const toggleTask = async task => {
    setError('');
    try {
      const { data: saved } = await setTaskEnabled(task.id, !task.enabled);
      ++requestId.current;
      setTasks(current => current.map(item => item.id === task.id
        ? { ...item, ...saved, sort_order: item.sort_order, next_run_at: null } : item));
    } catch (err) {
      setError(err.message || '更新任务失败');
    }
  };

  const reorderTasks = async ids => {
    if (reorderInFlight.current) return;
    const previousIds = tasks.map(task => task.id);
    if (ids.length !== previousIds.length || new Set(ids).size !== ids.length || ids.some(id => !previousIds.includes(id))) {
      throw new Error('任务列表已变化，请刷新后重试');
    }
    if (ids.every((id, index) => id === previousIds[index])) return;
    const previousOrders = new Map(tasks.map(task => [task.id, task.sort_order]));
    const positions = new Map(ids.map((id, index) => [id, index]));
    reorderInFlight.current = true;
    setReordering(true);
    setError('');
    // 先同步 React 中的顺序，避免执行状态更新时网格回到拖动前的位置。
    ++requestId.current;
    setTasks(current => [...current].sort((a, b) => positions.get(a.id) - positions.get(b.id))
      .map(task => ({ ...task, sort_order: positions.get(task.id) })));
    try {
      await persistTaskOrder(ids);
    } catch (err) {
      const previousPositions = new Map(previousIds.map((id, index) => [id, index]));
      // 仅恢复顺序，保留保存期间更新的任务执行结果。
      setTasks(current => [...current].sort((a, b) => (previousPositions.get(a.id) ?? Infinity) - (previousPositions.get(b.id) ?? Infinity))
        .map(task => ({ ...task, sort_order: previousOrders.get(task.id) ?? task.sort_order })));
      throw err;
    } finally {
      reorderInFlight.current = false;
      setReordering(false);
    }
  };

  const runTask = async taskId => {
    // ref 立即生效，阻止 React 更新状态前的连续点击。
    if (activeTask.current !== null) return;
    activeTask.current = taskId;
    setPendingTaskId(taskId);
    setError('');
    try {
      const { data: result } = await executeTask(taskId);
      ++requestId.current;
      setTasks(current => current.map(task => task.id === taskId ? { ...task, result } : task));
    } catch (err) {
      setError(err.message || '任务执行失败');
      // 失败响应只有错误文本，重新读取服务端保存的完整执行结果。
      try {
        await loadTasks();
      } catch {
        // 保留原始执行错误，用户仍可手动刷新。
      }
    } finally {
      // 等待状态只由 pendingTaskId 表示，不把临时状态写进后端结果。
      activeTask.current = null;
      setPendingTaskId(null);
    }
  };

  return {
    tasks, scripts, settings, latestUpdateTimes, latestDataStatus, loading, error, reordering,
    runningTaskId: pendingTaskId ?? tasks.find(task => task.result?.status === 'running')?.id ?? null,
    runTask, reload, saveTask, removeTask, toggleTask, reorderTasks
  };
}
