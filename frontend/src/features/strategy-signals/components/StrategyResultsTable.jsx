import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ClientSideRowModelModule, CellStyleModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import moment from 'moment';
import { getDailyBarsApi } from '@/api/quantide/api.js';
import StockKlineChart from '@/components/TradingView/StockKlineChart.jsx';
import styles from './StrategyResultsTable.module.css';
import { transformHistory } from '../utils/tableColumns.jsx';

const modules = [ClientSideRowModelModule, CellStyleModule];
const themeDark = themeQuartz.withPart(colorSchemeDark).withParams({ backgroundColor: '#09090b' });
const KLINE_ROW_HEIGHT = 586;
const historyCache = new Map();

function useStrategyStockKline() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestIdRef = useRef(0);

  const loadKline = useCallback(async symbol => {
    if (!symbol) return;
    const requestId = ++requestIdRef.current;
    const cachedRows = historyCache.get(symbol);
    if (cachedRows) {
      setData({ dataSource: '本地历史行情', adjustLabel: '前复权', rows: cachedRows });
      return;
    }

    setLoading(true);
    setError('');
    try {
      const response = await getDailyBarsApi({
        symbol,
        start: moment().subtract(1, 'year').format('YYYY-MM-DD'),
        end: moment().format('YYYY-MM-DD')
      });
      const rows = transformHistory(response?.data);
      historyCache.set(symbol, rows);
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

function StrategyKlineRow({ data }) {
  const stock = data.stock;
  const [period, setPeriod] = useState('daily');
  const { data: klineData, loading, error, loadKline } = useStrategyStockKline();

  useEffect(() => {
    loadKline(stock.symbol);
  }, [loadKline, stock.symbol]);

  return (
    <div className={styles.klineRow}>
      <StockKlineChart
        stock={{ ...stock, code: stock.symbol }}
        data={klineData}
        loading={loading}
        error={error}
        period={period}
        onPeriodChange={setPeriod}
        enableMouseWheelZoom={false}
      />
    </div>
  );
}

function keepKlineRowsWithStocks({ nodes }) {
  const klineRowsByStock = new Map(
    nodes.filter(node => node.data?.rowType === 'kline').map(node => [node.data.parentRowId, node])
  );
  const stockRows = nodes.filter(node => node.data?.rowType !== 'kline');
  nodes.length = 0;
  stockRows.forEach(stockRow => {
    nodes.push(stockRow);
    const klineRow = klineRowsByStock.get(stockRow.data.rowId);
    if (klineRow) nodes.push(klineRow);
  });
}

export default function StrategyResultsTable({ columnDefs, rows, loading }) {
  const rowData = useMemo(
    () =>
      rows.flatMap((row, index) => {
        const rowKey = `${row.symbol}-${index}`;
        const stockRowId = `stock-${rowKey}`;
        return [
          { ...row, rowId: stockRowId },
          { rowType: 'kline', rowId: `kline-${rowKey}`, parentRowId: stockRowId, stock: row }
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
          fullWidthCellRenderer={StrategyKlineRow}
          getRowHeight={params => (params.data?.rowType === 'kline' ? KLINE_ROW_HEIGHT : undefined)}
          getRowId={params => params.data.rowId}
          isFullWidthRow={params => params.rowNode.data?.rowType === 'kline'}
          loading={loading}
          overlayNoRowsTemplate="<span>当前策略暂无命中股票</span>"
          postSortRows={keepKlineRowsWithStocks}
          suppressCellFocus
        />
      </AgGridProvider>
    </div>
  );
}
