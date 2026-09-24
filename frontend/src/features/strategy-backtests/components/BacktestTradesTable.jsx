import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ClientSideRowModelModule, CellStyleModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import moment from 'moment';
import { getDailyBarsApi } from '@/api/quantide/api.js';
import StockKlineChart from '@/components/TradingView/StockKlineChart.jsx';
import { tradeColumnDefs, transformHistory } from '../utils/backtestFormatters.jsx';
import styles from './BacktestTradesTable.module.css';

const modules = [ClientSideRowModelModule, CellStyleModule];
const themeDark = themeQuartz.withPart(colorSchemeDark).withParams({ backgroundColor: '#09090b' });
const KLINE_ROW_HEIGHT = 586;
const historyCache = new Map();
const historyRequests = new Map();

function useTradeKline(symbol, trades) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  const loadKline = useCallback(async () => {
    if (!symbol) return;
    const tradeDates = trades.map(trade => moment(trade.trade_date)).filter(date => date.isValid());
    const firstTradeDate = moment.min(tradeDates);
    const lastTradeDate = moment.max(tradeDates);
    // 获取交易日期的前后两个月作为K线数据的时间范围
    const start = firstTradeDate.clone().subtract(2, 'months').format('YYYY-MM-DD');
    const end = lastTradeDate.clone().add(2, 'months').format('YYYY-MM-DD');
    const cacheKey = `${symbol}:${start}:${end}`;
    const cachedRows = historyCache.get(cacheKey);
    if (cachedRows) {
      setData({ dataSource: '本地历史行情', adjustLabel: '前复权', rows: cachedRows });
      return;
    }

    const requestId = ++requestIdRef.current;
    setLoading(true);
    setError('');
    try {
      let historyRequest = historyRequests.get(cacheKey);
      if (!historyRequest) {
        historyRequest = getDailyBarsApi({ symbol, start, end })
          .then(response => {
            const rows = transformHistory(response?.data);
            historyCache.set(cacheKey, rows);
            return rows;
          })
          .finally(() => historyRequests.delete(cacheKey));
        historyRequests.set(cacheKey, historyRequest);
      }
      const rows = await historyRequest;
      if (requestId === requestIdRef.current) {
        setData({ dataSource: '本地历史行情', adjustLabel: '前复权', rows });
      }
    } catch (requestError) {
      if (requestId === requestIdRef.current) setError(requestError.message || 'K 线加载失败');
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, [symbol, trades]);

  useEffect(() => {
    loadKline();
    return () => {
      requestIdRef.current += 1;
    };
  }, [loadKline]);

  return { data, loading, error };
}

function TradeKlineRow({ data }) {
  const [period, setPeriod] = useState('daily');
  const { stock, symbolTrades } = data;
  const { data: klineData, loading, error } = useTradeKline(stock.symbol, symbolTrades);
  const markers = useMemo(
    () => symbolTrades.map(item => ({ time: item.trade_date, side: item.side, price: item.price })),
    [symbolTrades]
  );

  return (
    <div className={styles.klineRow}>
      <StockKlineChart
        stock={stock}
        data={klineData}
        loading={loading}
        error={error}
        period={period}
        onPeriodChange={setPeriod}
        markers={markers}
        enableMouseWheelZoom={false}
      />
    </div>
  );
}

function keepStockGroupsTogether({ nodes }) {
  const klineRowsBySymbol = new Map(
    nodes.filter(node => node.data?.rowType === 'kline').map(node => [node.data.symbol, node])
  );
  const tradeGroups = new Map();

  nodes.forEach(node => {
    if (node.data?.rowType === 'kline') return;
    const symbol = node.data?.symbol;
    const symbolRows = tradeGroups.get(symbol) || [];
    symbolRows.push(node);
    tradeGroups.set(symbol, symbolRows);
  });

  nodes.length = 0;
  tradeGroups.forEach((tradeRows, symbol) => {
    nodes.push(...tradeRows);
    const klineRow = klineRowsBySymbol.get(symbol);
    if (klineRow) nodes.push(klineRow);
  });
}

export default function BacktestTradesTable({ trades, loading }) {
  const rowData = useMemo(() => {
    const tradesBySymbol = new Map();
    trades.forEach(trade => {
      const symbolTrades = tradesBySymbol.get(trade.symbol) || [];
      symbolTrades.push(trade);
      tradesBySymbol.set(trade.symbol, symbolTrades);
    });

    const sortedGroups = [...tradesBySymbol.entries()]
      .map(([symbol, symbolTrades]) => [
        symbol,
        [...symbolTrades].sort((left, right) => String(left.trade_date).localeCompare(String(right.trade_date)))
      ])
      .sort(([, leftTrades], [, rightTrades]) =>
        String(leftTrades[0]?.trade_date).localeCompare(String(rightTrades[0]?.trade_date))
      );

    return sortedGroups.flatMap(([symbol, symbolTrades]) => {
      const tradeRows = symbolTrades.map((trade, index) => ({
        ...trade,
        rowId: `trade-${symbol}-${trade.trade_date}-${trade.side}-${index}`
      }));
      const stock = { name: symbolTrades[0]?.name, symbol };

      return [
        ...tradeRows,
        {
          rowType: 'kline',
          rowId: `kline-${symbol}`,
          symbol,
          stock,
          symbolTrades
        }
      ];
    });
  }, [trades]);

  return (
    <div className={styles.grid}>
      <AgGridProvider modules={modules}>
        <AgGridReact
          theme={themeDark}
          rowData={rowData}
          columnDefs={tradeColumnDefs}
          defaultColDef={{ resizable: true, sortable: true }}
          fullWidthCellRenderer={TradeKlineRow}
          getRowHeight={params => (params.data?.rowType === 'kline' ? KLINE_ROW_HEIGHT : undefined)}
          getRowId={params => params.data.rowId}
          isFullWidthRow={params => params.rowNode.data?.rowType === 'kline'}
          loading={loading}
          overlayNoRowsTemplate="<span>当前回测区间暂无交易记录</span>"
          postSortRows={keepStockGroupsTogether}
          suppressCellFocus
        />
      </AgGridProvider>
    </div>
  );
}
