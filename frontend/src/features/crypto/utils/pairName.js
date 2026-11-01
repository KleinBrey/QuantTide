export const QUOTE_ASSETS = ['USDT', 'USDC', 'FDUSD', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB', 'EUR', 'TRY'];

export function pairName(symbol) {
  // 只拆分显示名称，请求、分组和排序仍使用原始永续合约代码。
  const quote = QUOTE_ASSETS.find(asset => symbol.length > asset.length && symbol.endsWith(asset));
  return quote ? `${symbol.slice(0, -quote.length)} / ${quote}` : symbol;
}
