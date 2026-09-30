import { useEffect, useMemo } from 'react';
import { ClientSideRowModelModule, CellStyleModule, colorSchemeDark, themeQuartz } from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import AShareStockKlinePanel from './AShareStockKlinePanel.jsx';
import { useAShareStockKline } from '../hooks/useAShareStockKline.js';
import styles from './AShareMarketTable.module.css';

// 要用什么功能就加入什么模块
const modules = [ClientSideRowModelModule, CellStyleModule];

const themeDarkBlue = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#09090b'
});

const KLINE_ROW_HEIGHT = 586;

function formatChangePercent(value) {
  if (value === null || value === undefined || value === '') return '-';

  const change = Number(value);
  if (!Number.isFinite(change)) return '-';

  const sign = change > 0 ? '+' : '';
  return `${sign}${change.toFixed(2)}%`;
}

function ChangePercentCell(params) {
  // 涨跌幅使用快照最新值
  const change = Number(params.data.todaySnapshot.price_change_ratio_pct);
  const color = change > 0 ? '#f04451' : change < 0 ? '#24bd7a' : undefined;
  return <span style={{ color }}>{formatChangePercent(change)}</span>;
}

const COLUMN_DEFS = [
  { headerName: '股票', field: 'name', flex: 1, cellStyle: { color: '#ff7f50' } },
  { headerName: '代码', field: 'symbol', flex: 1 },
  {
    headerName: '涨幅%',
    field: 'change_pct',
    flex: 0.7,
    minWidth: 92,
    cellRenderer: ChangePercentCell
  },
  { headerName: '热度排名', field: 'rank', flex: 1 }
];

// K线图组件
function AShareMarketKlineRow({ data }) {
  const stock = data.stock;
  const { data: klineData, loading, error, loadKline } = useAShareStockKline();

  useEffect(() => {
    loadKline(stock.symbol, stock.todaySnapshot);
  }, [loadKline, stock]);

  return (
    <div className={styles.klineRow}>
      <AShareStockKlinePanel
        stock={stock}
        data={klineData}
        loading={loading}
        error={error}
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

export default function AShareMarketTable({ rows, loading }) {
  // 构造K线图数据行
  const rowData = useMemo(
    () =>
      rows.flatMap((row, index) => {
        const rowKey = `${row.symbol}-${index}`;
        const stockRowId = `stock-${rowKey}`;
        return [
          {
            ...row,
            rowId: stockRowId
          },
          {
            rowType: 'kline',
            rowId: `kline-${rowKey}`,
            parentRowId: stockRowId,
            stock: row
          }
        ];
      }),
    [rows]
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
              fullWidthCellRenderer={AShareMarketKlineRow}
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
