import { useCallback, useEffect, useRef, useState } from 'react';

import { getSignalResults, getSignals } from '../api/signalsApi.js';

import { columnDefs as columnDefsConfig } from '../utils/tableColumns.jsx';

export function useSignals() {
  const [signals, setSignals] = useState([]);
  const [activeSignalId, setActiveSignalId] = useState('');
  const [result, setResult] = useState(null);
  const [columnDefs, setColumnDefs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);
  const resultRequestControllerRef = useRef(null);

  const loadSignalResult = useCallback(async signalId => {
    resultRequestControllerRef.current?.abort();
    const controller = new AbortController();
    resultRequestControllerRef.current = controller;
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      const payload = await getSignalResults(signalId, { signal: controller.signal });
      if (requestId === requestIdRef.current) setResult(payload);
    } catch (requestError) {
      if (requestError.name !== 'AbortError' && requestId === requestIdRef.current) {
        setError(requestError.message || '信号结果加载失败');
      }
    } finally {
      if (resultRequestControllerRef.current === controller) {
        resultRequestControllerRef.current = null;
        if (!controller.signal.aborted && requestId === requestIdRef.current) {
          setLoading(false);
        }
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    async function initialize() {
      try {
        const payload = await getSignals({ signal: controller.signal });
        const signalItems = Array.isArray(payload?.items) ? payload.items : [];
        const firstSignalId = signalItems[0]?.id || '';
        setColumnDefs(columnDefsConfig[firstSignalId] || columnDefsConfig['default']);
        setSignals(signalItems);
        setActiveSignalId(firstSignalId);
        if (firstSignalId) {
          await loadSignalResult(firstSignalId);
        } else {
          setLoading(false);
        }
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || '信号列表加载失败');
          setLoading(false);
        }
      }
    }

    initialize();
    return () => {
      controller.abort();
      resultRequestControllerRef.current?.abort();
      resultRequestControllerRef.current = null;
      requestIdRef.current += 1;
    };
  }, [loadSignalResult]);

  const selectSignal = useCallback(
    signalId => {
      if (!signalId || signalId === activeSignalId) return;
      setActiveSignalId(signalId);
      setColumnDefs(columnDefsConfig[signalId] || columnDefsConfig['default']);
      setResult(null);
      loadSignalResult(signalId);
    },
    [activeSignalId, loadSignalResult]
  );

  return {
    signals,
    activeSignalId,
    result,
    loading,
    error,
    columnDefs,
    selectSignal,
    refresh: () => activeSignalId && loadSignalResult(activeSignalId)
  };
}
