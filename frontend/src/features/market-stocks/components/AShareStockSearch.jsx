import { useEffect, useState } from 'react';
import { Loader2, Plus } from 'lucide-react';
import { searchWatchlistStocksApi } from '@/api/quantide/api.js';
import styles from './MarketStockBrowser.module.css';

export default function AShareStockSearch({ inputRef, stocks, disabled, onAdd }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setResults([]);
    setError('');
    setSearching(Boolean(query.trim()));
    if (!query.trim()) return undefined;
    const timer = setTimeout(async () => {
      try {
        const response = await searchWatchlistStocksApi({ q: query.trim(), market: 'CN', limit: 30 });
        if (!cancelled) setResults(response.data);
      } catch (requestError) {
        if (!cancelled) setError(requestError.message || '搜索失败，请重试');
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const add = async stock => {
    setError('');
    try {
      await onAdd(stock);
    } catch (requestError) {
      setError(requestError.message || '添加失败，请重试');
    }
  };

  return (
    <div>
      <label>
        搜索 A 股
        <input
          ref={inputRef}
          aria-label="搜索 A 股"
          autoComplete="off"
          maxLength={100}
          disabled={disabled}
          placeholder="输入名称或代码，如 贵州茅台 / 600519"
          value={query}
          onChange={event => setQuery(event.target.value)}
        />
      </label>
      {error && (
        <p className={styles.formError} role="alert">
          {error}
        </p>
      )}
      <div className={styles.stockSearchResults} aria-label="A 股搜索结果" aria-busy={searching}>
        {searching ? (
          <p className={styles.searchHint}>
            <Loader2 className="dashboard-spin" size={14} />
            搜索中…
          </p>
        ) : (
          results.map(stock => {
            const added = stocks.some(item => item.symbol === stock.symbol);
            return (
              <button
                key={stock.symbol}
                className={styles.stockSearchResult}
                type="button"
                aria-label={`添加 ${stock.name} ${stock.symbol}`}
                disabled={disabled || added}
                onClick={() => add(stock)}
              >
                <span>
                  <strong>{stock.name}</strong>
                  <small>{stock.symbol}</small>
                </span>
                {added ? <small>已添加</small> : <Plus size={15} />}
              </button>
            );
          })
        )}
        {!searching && !error && !results.length && (
          <p className={styles.searchHint}>
            {query.trim() ? '未找到股票，请检查名称、代码或同步股票列表' : '搜索后点击股票，加入当前分组'}
          </p>
        )}
      </div>
    </div>
  );
}
