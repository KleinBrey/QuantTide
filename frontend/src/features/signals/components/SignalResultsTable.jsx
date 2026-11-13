import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ClientSideRowModelModule, CellStyleModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import moment from 'moment';
import { getDailyBarsApi } from '@/api/quantide/api.js';
import StockKlineChart from '@/components/tradingView/StockKlineChart.jsx';
import styles from './SignalResultsTable.module.css';
import { transformHistory } from '../utils/tableColumns.jsx';

const modules = [ClientSideRowModelModule, CellStyleModule];
const themeDark = themeQuartz.withPart(colorSchemeDark).withParams({ backgroundColor: '#09090b' });
const KLINE_ROW_HEIGHT = 586;
const historyCache = new Map();

function useSignalStockKline() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  const loadKline = useCallback(async (symbol, start, end) => {
    if (!symbol) return;
    const requestId = ++requestIdRef.current;
    const cacheKey = `${symbol}:${start}:${end}`;
    setError('');
    const cachedRows = historyCache.get(cacheKey);
    if (cachedRows) {
      setLoading(false);
      setData({ dataSource: '本地历史行情', adjustLabel: '前复权', rows: cachedRows });
      return;
    }

    setLoading(true);
    try {
      const response = await getDailyBarsApi({ symbol, start, end });
      const rows = transformHistory(response?.data);
      if (historyCache.size >= 100) historyCache.delete(historyCache.keys().next().value);
      historyCache.set(cacheKey, rows);
      if (requestId === requestIdRef.current) {
        setData({ dataSource: '本地历史行情', adjustLabel: '前复权', rows });
      }
    } catch (requestError) {
      if (requestId === requestIdRef.current) {
        setError(requestError.message || 'K 线加载失败');
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    return () => {
      requestIdRef.current += 1;
    };
  }, []);

  return { data, loading, error, loadKline };
}

function SignalKlineRow({ data }) {
  const { stock, hits } = data;
  const [period, setPeriod] = useState('daily');
  const { data: klineData, loading, error, loadKline } = useSignalStockKline();

  const start = moment(hits[0].signal_date).subtract(3, 'months').format('YYYY-MM-DD');
  const end = moment(hits.at(-1).signal_date).add(3, 'months').format('YYYY-MM-DD');
  const markers = useMemo(() => hits.map(hit => ({ time: hit.signal_date, side: 'SIGNAL' })), [hits]);

  useEffect(() => {
    loadKline(stock.symbol, start, end);
  }, [loadKline, stock.symbol, start, end]);

  return (
    <div className={styles.klineRow}>
      <StockKlineChart
        stock={{ ...stock, code: stock.symbol }}
        data={klineData}
        loading={loading}
        error={error}
        period={period}
        onPeriodChange={setPeriod}
        markers={markers}
        enableMouseWheelZoom={false}
        alignDataLeft
      />
    </div>
  );
}

function groupByStock(rows, getRow = row => row) {
  const groups = new Map();
  rows.forEach(row => {
    const { symbol } = getRow(row);
    if (!groups.has(symbol)) groups.set(symbol, []);
    groups.get(symbol).push(row);
  });
  return groups;
}

function keepKlineRowsWithStocks({ nodes }) {
  const charts = new Map(
    nodes.filter(node => node.data.rowType === 'kline').map(node => [node.data.symbol, node])
  );
  const groups = groupByStock(nodes.filter(node => node.data.rowType !== 'kline'), node => node.data);
  nodes.length = 0;
  groups.forEach((hits, symbol) => {
    nodes.push(...hits);
    const chart = charts.get(symbol);
    if (chart) nodes.push(chart);
  });
}

export default function SignalResultsTable({ columnDefs, rows, loading, emptyMessage }) {
  const rowData = useMemo(
    () => [...groupByStock(rows)].flatMap(([symbol, matches]) => {
      const hits = [...matches].sort((a, b) => a.signal_date.localeCompare(b.signal_date));
      return [
        ...hits.map(hit => ({ ...hit, rowId: `signal-${symbol}-${hit.signal_date}` })),
        { rowType: 'kline', rowId: `kline-${symbol}`, symbol, stock: hits.at(-1), hits }
      ];
    }),
    [rows]
  );

  return (
    <div className={styles.grid}>
      <AgGridProvider modules={modules}>
        <AgGridReact
          theme={themeDark}
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={{ resizable: true, sortable: true }}
          fullWidthCellRenderer={SignalKlineRow}
          getRowHeight={params => (params.data?.rowType === 'kline' ? KLINE_ROW_HEIGHT : undefined)}
          getRowId={params => params.data.rowId}
          isFullWidthRow={params => params.rowNode.data?.rowType === 'kline'}
          loading={loading}
          overlayNoRowsTemplate={`<span>${emptyMessage}</span>`}
          postSortRows={keepKlineRowsWithStocks}
          suppressCellFocus
        />
      </AgGridProvider>
    </div>
  );
}
