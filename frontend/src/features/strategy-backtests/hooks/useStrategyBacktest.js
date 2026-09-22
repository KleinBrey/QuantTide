import { useCallback, useEffect, useRef, useState } from 'react';
import { getConfirmedVolumeBreakoutBacktest } from '../api/backtestApi.js';

export function useStrategyBacktest() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const controllerRef = useRef(null);

  const loadBacktest = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError('');

    try {
      const payload = await getConfirmedVolumeBreakoutBacktest({ signal: controller.signal });
      if (!controller.signal.aborted) setResult(payload);
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
    loadBacktest();
    return () => controllerRef.current?.abort();
  }, [loadBacktest]);

  return { result, loading, error, refresh: loadBacktest };
}
