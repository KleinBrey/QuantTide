import { useEffect, useMemo } from 'react';
import { CellStyleModule, ClientSideRowModelModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import StockKlinePanel from './StockKlinePanel.jsx';
import { useStockKline } from '../hooks/useStockKline.js';
import { useStockPool } from '../hooks/useStockPool.js';
import { stockPoolSymbol } from '../utils/stockPool.js';
import styles from './RankingTable.module.css';

const modules = [ClientSideRowModelModule, CellStyleModule];

const themeDarkBlue = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#09090b'
});

const KLINE_ROW_HEIGHT = 586;

function stockSymbol(stock) {
  return stock?.thscode || stock?.code || '';
}

function RankingKlineRow({ data }) {
  const stock = data.stock;
  const marketId = data.marketId;
  const { data: klineData, loading, error, loadKline } = useStockKline();

  useEffect(() => {
    loadKline(stockSymbol(stock), marketId);
  }, [loadKline, marketId, stock]);

  return (
    <div className={styles.klineRow}>
      <StockKlinePanel stock={stock} data={klineData} loading={loading} error={error} enableMouseWheelZoom={false} />
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

function formatChangePercent(value) {
  if (value === null || value === undefined || value === '') return '-';

  const change = Number(value);
  if (!Number.isFinite(change)) return '-';

  const sign = change > 0 ? '+' : '';
  return `${sign}${change.toFixed(2)}%`;
}

function ChangePercentCell(params) {
  // 涨跌幅使用快照最新值
  const change = params.data.change_pct;
  const color = change > 0 ? '#f04451' : change < 0 ? '#24bd7a' : undefined;
  return <span style={{ color }}>{formatChangePercent(change)}</span>;
}

const COLUMN_DEFS = [
  { headerName: '股票', field: 'name', flex: 1 },
  { headerName: '代码', field: 'symbol', flex: 1 },
  {
    headerName: '涨幅%',
    field: 'change_pct',
    flex: 0.5,
    minWidth: 100,
    cellRenderer: ChangePercentCell
  }
];

function StockPoolCell({ data, onAddStock }) {
  const { inStockPool, poolPending, poolDisabled, poolSymbol } = data;
  return (
    <button
      type="button"
      className={`${styles.poolFlag} ${inStockPool ? styles.poolFlagActive : ''}`}
      aria-pressed={inStockPool}
      aria-busy={poolPending}
      disabled={inStockPool || poolDisabled || poolPending || !poolSymbol}
      data-stock-pool-symbol={poolSymbol}
      onClick={event => {
        event.stopPropagation();
        onAddStock(data);
      }}
    >
      <svg width="16" height="18" viewBox="0 0 16 18" aria-hidden="true">
        <path d="M1 2h14l-4 7 4 7H1z" fill="currentColor" />
      </svg>
    </button>
  );
}

export default function RankingTable({ rows, loading, marketId = 'a-share', showKline = false }) {
  const {
    enabled,
    symbols,
    pending,
    loading: poolLoading,
    ready: poolReady,
    error: poolError,
    refresh: refreshPool,
    addStock
  } = useStockPool(marketId, rows);
  const columnDefs = useMemo(
    () =>
      enabled
        ? [
            {
              colId: 'stock_pool',
              headerName: '',
              width: 36,
              minWidth: 36,
              maxWidth: 36,
              sortable: false,
              resizable: false,
              suppressMovable: true,
              lockPosition: 'left',
              cellClass: styles.poolFlagCell,
              cellRenderer: StockPoolCell,
              cellRendererParams: { onAddStock: addStock }
            },
            ...COLUMN_DEFS
          ]
        : COLUMN_DEFS,
    [enabled, addStock]
  );
  // 普通状态只展示股票行；榜单进入全屏后，才为每只股票插入对应的 K 线行。
  const rowData = useMemo(
    () =>
      rows.flatMap((row, index) => {
        const rowKey = `${stockSymbol(row) || 'stock'}-${index}`;
        const stockRowId = `stock-${rowKey}`;
        const poolSymbol = stockPoolSymbol(row, marketId);
        const stockRow = {
          ...row,
          rowId: stockRowId,
          poolSymbol,
          inStockPool: symbols.has(poolSymbol),
          poolPending: pending.has(poolSymbol),
          poolDisabled: !poolReady
        };

        if (!showKline) return [stockRow];

        return [
          stockRow,
          {
            rowType: 'kline',
            rowId: `kline-${rowKey}`,
            parentRowId: stockRowId,
            marketId,
            stock: row
          }
        ];
      }),
    [marketId, rows, showKline, symbols, pending, poolReady]
  );

  return (
    <div className={styles.table}>
      {poolError && (
        <div className={styles.poolError} role="alert">
          <span>{poolError}</span>
          <button type="button" onClick={refreshPool} disabled={poolLoading}>
            重试
          </button>
        </div>
      )}
      <div className={styles.grid}>
        <AgGridProvider modules={modules}>
          <div style={{ height: '100%', width: '100%' }}>
            <AgGridReact
              theme={themeDarkBlue}
              rowData={rowData}
              columnDefs={columnDefs}
              defaultColDef={{ resizable: true, sortable: true }}
              fullWidthCellRenderer={RankingKlineRow}
              getRowHeight={params => (params.data?.rowType === 'kline' ? KLINE_ROW_HEIGHT : undefined)}
              getRowId={params => params.data.rowId}
              isFullWidthRow={params => params.rowNode.data?.rowType === 'kline'}
              loading={loading}
              postSortRows={keepKlineRowsWithStocks}
              suppressCellFocus
              enableCellTextSelection
            />
          </div>
        </AgGridProvider>
      </div>
    </div>
  );
}
