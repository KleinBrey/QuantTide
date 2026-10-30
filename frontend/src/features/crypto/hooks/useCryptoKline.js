import { useEffect, useState } from 'react';
import { getCryptoBars } from '../api/cryptoApi.js';

export function useCryptoKline(symbol, revision) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError('');
    if (!symbol) {
      setLoading(false);
      return;
    }
    setLoading(true);
    getCryptoBars(symbol).then(({ data }) => {
      if (!cancelled) setData({ rows: data.map(row => ({ ...row, date: row.trade_date.slice(0, 10) })) });
    }).catch(error => {
      if (!cancelled) setError(error.message);
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    // 快速切换交易对时，忽略上一次请求的结果。
    return () => { cancelled = true; };
  }, [symbol, revision]);

  // 低价交易对增加小数位，高价交易对保持紧凑显示。
  const lowestPrice = Math.min(...(data?.rows || []).map(row => row.low).filter(price => price > 0));
  const pricePrecision = lowestPrice >= 1 ? 2 : Math.min(8, Math.ceil(-Math.log10(lowestPrice)) + 3);
  return { data, loading, error, pricePrecision };
}
