import styles from './MarketBrowser.module.css';

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatPrice(value, market) {
  const price = finiteNumber(value);
  if (price === null) return '—';
  if (market === 'CRYPTO') {
    return price.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: Math.abs(price) < 1 ? 8 : 2,
      useGrouping: false
    });
  }
  return price.toFixed(market === 'HK' ? 3 : 2);
}

export default function AssetListItemContent({ name, symbol, price, change_pct, quote_date, market }) {
  const displaySymbol = market === 'FUTURES' ? symbol?.split('.')[0] : symbol;
  const change = finiteNumber(change_pct);
  const tone = change > 0 ? styles.quoteUp : change < 0 ? styles.quoteDown : '';
  const changeText = change === null ? '—' : `${change > 0 ? '+' : ''}${change.toFixed(2)}%`;
  const quoteTitle = quote_date
    ? `本地日 K · ${String(quote_date).slice(0, 10)} · 涨跌幅较上一交易日收盘价`
    : '暂无本地行情，请同步日 K';

  return (
    <>
      <div className={styles.assetIdentity}>
        <span className={styles.assetName}>{name || displaySymbol}</span>
        {market !== 'CRYPTO' && <small className={styles.assetSymbol}>{displaySymbol}</small>}
      </div>
      <div className={`${styles.assetQuote} ${tone}`} title={quoteTitle}>
        <span className={styles.assetPrice} aria-label="最新价">{formatPrice(price, market)}</span>
        <span className={styles.assetChange} aria-label="涨跌幅">{changeText}</span>
      </div>
    </>
  );
}
