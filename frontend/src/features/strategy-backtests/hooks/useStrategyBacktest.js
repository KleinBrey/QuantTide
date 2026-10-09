import { useCallback, useEffect, useRef, useState } from 'react';
import { format, subMonths } from 'date-fns';
import { getStrategyBacktest, getBacktestStrategies } from '../api/backtestApi.js';

function createDefaultParams() {
  const today = new Date();
  return {
    strategy: '',
    start_date: format(subMonths(today, 6), 'yyyy-MM-dd'),
    end_date: format(today, 'yyyy-MM-dd'),
    max_positions: 20,
    max_position_pct: 5
  };
}

export function useStrategyBacktest() {
  const [strategies, setStrategies] = useState([]);
  const [params, setParams] = useState(createDefaultParams);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const controllerRef = useRef(null);

  const loadBacktest = useCallback(async values => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError('');

    try {
      const payload = await getStrategyBacktest(values, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setResult(payload);
      }
    } catch (requestError) {
      if (requestError.name !== 'AbortError') {
        setError(requestError.message || '策略回测结果加载失败');
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    async function initialize() {
      try {
        const available = await getBacktestStrategies({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setStrategies(available);
        const values = { ...createDefaultParams(), strategy: available[0].id };
        setParams(values);
      } catch (requestError) {
        if (!controller.signal.aborted) {
          setError(requestError.message || '回测策略列表加载失败');
        }
      }
    }

    initialize();
    return () => {
      controller.abort();
      controllerRef.current?.abort();
    };
  }, [loadBacktest]);

  return { strategies, result, loading, error, params, setParams, runBacktest: loadBacktest };
}
