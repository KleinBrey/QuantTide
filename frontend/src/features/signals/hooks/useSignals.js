import moment from 'moment';
import { useCallback, useEffect, useRef, useState } from 'react';

import { getSignalResults, getSignals } from '../api/signalsApi.js';

import { columnDefs as columnDefsConfig } from '../utils/tableColumns.jsx';

function defaultRange() {
  const today = moment().utcOffset(8 * 60);
  return {
    startDate: today.clone().subtract(3, 'months').format('YYYY-MM-DD'),
    endDate: today.format('YYYY-MM-DD')
  };
}

export function useSignals() {
  const [scanMode, setScanMode] = useState('today');
  const [initialRange] = useState(defaultRange);
  const [range, setRange] = useState(initialRange);
  const validRange = scanMode === 'today' || Boolean(range.startDate && range.endDate && range.startDate <= range.endDate);
  const [signals, setSignals] = useState([]);
  const [activeSignalId, setActiveSignalId] = useState('');
  const [result, setResult] = useState(null);
  const [columnDefs, setColumnDefs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);
  const resultRequestControllerRef = useRef(null);
  const resultsCacheRef = useRef(new Map());

  const loadSignalResult = useCallback(async (signalId, mode, scanRange, force = false) => {
    resultRequestControllerRef.current?.abort();
    resultRequestControllerRef.current = null;
    const requestId = ++requestIdRef.current;
    setError('');
    if (mode === 'history' && (!scanRange.startDate || !scanRange.endDate || scanRange.startDate > scanRange.endDate)) {
      setResult(null);
      setLoading(false);
      setError('请选择有效的历史扫描日期范围');
      return;
    }
    const cacheKey = JSON.stringify([signalId, mode, mode === 'history' ? scanRange : null]);
    const cached = resultsCacheRef.current.get(cacheKey);
    setResult(cached || null);
    if (cached && !force) {
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    resultRequestControllerRef.current = controller;
    setLoading(true);
    try {
      const payload = await getSignalResults(signalId, { mode, ...scanRange, signal: controller.signal });
      if (requestId === requestIdRef.current) {
        resultsCacheRef.current.set(cacheKey, payload);
        setResult(payload);
      }
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
          await loadSignalResult(firstSignalId, 'today', initialRange);
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
  }, [initialRange, loadSignalResult]);

  const selectSignal = useCallback(
    signalId => {
      if (!signalId || signalId === activeSignalId || !validRange) return;
      setActiveSignalId(signalId);
      setColumnDefs(columnDefsConfig[signalId] || columnDefsConfig['default']);
      setResult(null);
      loadSignalResult(signalId, scanMode, range);
    },
    [activeSignalId, loadSignalResult, range, scanMode, validRange]
  );

  const selectMode = useCallback(mode => {
    if (!mode || mode === scanMode) return;
    setScanMode(mode);
    if (activeSignalId) loadSignalResult(activeSignalId, mode, range);
  }, [activeSignalId, loadSignalResult, range, scanMode]);

  return {
    scanMode,
    selectMode,
    signals,
    activeSignalId,
    result,
    loading,
    error,
    columnDefs,
    selectSignal,
    range,
    setRange,
    validRange,
    refresh: () => activeSignalId && validRange && loadSignalResult(activeSignalId, scanMode, range, true)
  };
}
