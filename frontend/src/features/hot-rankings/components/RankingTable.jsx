import { useEffect, useMemo } from 'react';
import { ClientSideRowModelModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import StockKlinePanel from './StockKlinePanel.jsx';
import { useStockKline } from '../hooks/useStockKline.js';
import styles from './RankingTable.module.css';

const modules = [ClientSideRowModelModule];

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
  const change = Number(params.data.change_pct);
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
    minWidth: 92,
    cellRenderer: ChangePercentCell
  },
  { headerName: '热度', field: 'hot_value', flex: 1 }
];

export default function RankingTable({ rows, loading, marketId = 'a-share', showKline = false }) {
  // 普通状态只展示股票行；榜单进入全屏后，才为每只股票插入对应的 K 线行。
  const rowData = useMemo(
    () =>
      rows.flatMap((row, index) => {
        const rowKey = `${stockSymbol(row) || 'stock'}-${index}`;
        const stockRowId = `stock-${rowKey}`;
        const stockRow = {
          ...row,
          rowId: stockRowId
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
    [marketId, rows, showKline]
  );

  return (
    <>
      <div className={styles.grid}>
        <AgGridProvider modules={modules}>
          <div style={{ height: '100%', width: '100%' }}>
            <AgGridReact
              theme={themeDarkBlue}
              rowData={rowData}
              columnDefs={COLUMN_DEFS}
              defaultColDef={{ resizable: true, sortable: true }}
              fullWidthCellRenderer={RankingKlineRow}
              getRowHeight={params => (params.data?.rowType === 'kline' ? KLINE_ROW_HEIGHT : undefined)}
              getRowId={params => params.data.rowId}
              isFullWidthRow={params => params.rowNode.data?.rowType === 'kline'}
              loading={loading}
              postSortRows={keepKlineRowsWithStocks}
              suppressCellFocus
            />
          </div>
        </AgGridProvider>
      </div>
    </>
  );
}
