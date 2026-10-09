import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ClientSideRowModelModule,
  ClientSideRowModelApiModule,
  RenderApiModule,
  RowApiModule,
  RowDragModule,
  RowSelectionModule,
  ScrollApiModule,
  colorSchemeDark,
  themeQuartz
} from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import { ChevronRight, ChevronsDown, ChevronsUp, FolderPlus, Loader2, Plus, RefreshCcw, Trash2, X } from 'lucide-react';
import { ContextMenu, Popover } from 'radix-ui';

import AShareStockSearch from './AShareStockSearch.jsx';
import styles from './MarketStockBrowser.module.css';

const modules = [
  ClientSideRowModelModule,
  ClientSideRowModelApiModule,
  RenderApiModule,
  RowApiModule,
  RowDragModule,
  RowSelectionModule,
  ScrollApiModule
];
const theme = themeQuartz.withPart(colorSchemeDark).withParams({
  accentColor: '#71717a',
  backgroundColor: '#111114',
  foregroundColor: '#d4d4d8',
  borderColor: '#27272a',
  wrapperBorder: false,
  rowBorder: false,
  columnBorder: false,
  rowHoverColor: 'transparent',
  selectedRowBackgroundColor: 'transparent',
  fontFamily: 'inherit',
  fontSize: 13,
  cellHorizontalPadding: 10
});
const columnDefs = [{ headerName: '股票', field: 'name', flex: 1, cellRenderer: StockCell }];
const defaultColDef = { sortable: false, resizable: false, suppressMovable: true };
const rowSelection = { mode: 'singleRow', checkboxes: false, enableClickSelection: 'enableSelection' };
const getRowId = params => params.data.symbol;

function StockDragPreview({ dragSource }) {
  const rowNode = dragSource.getDragItem().rowNode;
  const stockRow = dragSource.eElement.querySelector('[data-stock-row]') ?? dragSource.eElement;
  const { width, height } = stockRow.getBoundingClientRect();
  const { fontFamily, lineHeight } = window.getComputedStyle(dragSource.eElement);
  const selected = rowNode.isSelected();

  return (
    <div
      className={`${styles.stockDragPreview}${selected ? ` ${styles.stockDragPreviewSelected}` : ''}`}
      style={{ width, height, fontFamily, lineHeight }}
      aria-hidden="true"
    >
      <div className={styles.stockItem}>
        <span>{rowNode.data.name}</span>
        <small>{rowNode.data.symbol}</small>
      </div>
    </div>
  );
}

function StockCell({ data, context }) {
  const index = context.stocks.findIndex(stock => stock.symbol === data.symbol);
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild disabled={context.disabled}>
        <div data-stock-row className={styles.stockItem} title={`${data.name} · ${data.symbol}`}>
          <span>{data.name}</span>
          <small>{data.symbol}</small>
        </div>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content aria-label={`${data.name}操作`} className={styles.contextMenu} collisionPadding={8}>
          <ContextMenu.Sub>
            <ContextMenu.SubTrigger
              className={styles.menuItem}
              disabled={context.disabled || context.groups.length < 2}
            >
              <FolderPlus size={17} />
              加入分组
              <ChevronRight className={styles.submenuArrow} size={14} />
            </ContextMenu.SubTrigger>
            <ContextMenu.Portal>
              <ContextMenu.SubContent className={styles.contextMenu} collisionPadding={8}>
                {context.groups
                  .filter(group => group.id !== context.groupId)
                  .map(group => (
                    <ContextMenu.Item
                      key={group.id}
                      className={styles.menuItem}
                      onSelect={() => context.addToGroup(group.id, data)}
                    >
                      {group.name}
                    </ContextMenu.Item>
                  ))}
              </ContextMenu.SubContent>
            </ContextMenu.Portal>
          </ContextMenu.Sub>
          <ContextMenu.Separator className={styles.menuSeparator} />
          <ContextMenu.Item
            className={styles.menuItem}
            disabled={context.disabled || index === 0}
            onSelect={() => context.moveStock(data.symbol, 'first')}
          >
            <ChevronsUp size={18} />
            移到最前
          </ContextMenu.Item>
          <ContextMenu.Item
            className={styles.menuItem}
            disabled={context.disabled || index === context.stocks.length - 1}
            onSelect={() => context.moveStock(data.symbol, 'last')}
          >
            <ChevronsDown size={18} />
            移到最后
          </ContextMenu.Item>
          <ContextMenu.Separator className={styles.menuSeparator} />
          <ContextMenu.Item
            className={styles.menuItem}
            disabled={context.disabled}
            onSelect={() => context.removeStock(data.symbol)}
          >
            <Trash2 size={17} />
            移出当前分组
          </ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

export default function MarketStockList({
  marketId,
  stocks,
  selectedStock,
  setSelectedStock,
  loading,
  error,
  mutating,
  actionError,
  addStock,
  removeStock,
  moveStock,
  reorderStocks,
  groups,
  groupId,
  addToGroup,
  refresh
}) {
  const gridRef = useRef(null);
  const nameInputRef = useRef(null);
  const [addOpen, setAddOpen] = useState(false);
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [addError, setAddError] = useState('');
  const disabled = loading || mutating;
  const context = useMemo(
    () => ({ stocks, disabled, moveStock, removeStock, groups, groupId, addToGroup }),
    [stocks, disabled, moveStock, removeStock, groups, groupId, addToGroup]
  );

  const syncSelection = api => {
    if (selectedStock) api.getRowNode(selectedStock.symbol)?.setSelected(true);
  };

  useEffect(() => {
    const api = gridRef.current?.api;
    if (api && !api.isDestroyed()) api.refreshCells({ force: true });
  }, [context]);

  useEffect(() => {
    const api = gridRef.current?.api;
    if (!api || api.isDestroyed()) return;
    const node = api.getRowNode(selectedStock?.symbol);
    if (node) {
      node.setSelected(true);
      api.ensureNodeVisible(node);
    }
  }, [selectedStock]);

  const handleAdd = async event => {
    event.preventDefault();
    setAddError('');
    try {
      if (await addStock({ symbol: symbol.trim(), name: name.trim() })) {
        setAddOpen(false);
        setSymbol('');
        setName('');
      }
    } catch (requestError) {
      setAddError(requestError.message || '添加股票失败，请重试');
    }
  };

  const handleDragEnd = ({ api }) => {
    // Managed dragging commits the drop after dispatching rowDragEnd.
    queueMicrotask(() => {
      if (api.isDestroyed()) return;
      const ordered = [];
      api.forEachNodeAfterFilterAndSort(node => ordered.push(node.data));
      if (ordered.length === stocks.length) reorderStocks(ordered);
    });
  };

  return (
    <>
      <div className={styles.listHeader}>
        <span>名称 / 代码</span>
        <div className={styles.listActions} aria-busy={loading}>
          <strong>{stocks.length}</strong>
          <button
            aria-label="刷新股票列表"
            className={styles.closeButton}
            disabled={disabled}
            onClick={refresh}
            title="刷新列表"
            type="button"
          >
            <RefreshCcw className={loading ? 'dashboard-spin' : undefined} size={14} />
          </button>
          <Popover.Root
            open={addOpen}
            onOpenChange={open => {
              if (mutating) return;
              setAddOpen(open);
              setAddError('');
            }}
          >
            <Popover.Trigger asChild>
              <button aria-label="添加股票" className={styles.addButton} disabled={disabled || !groupId} type="button">
                <Plus size={14} />
                添加股票
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                align="start"
                aria-label="添加股票"
                className={styles.addPopover}
                collisionPadding={8}
                sideOffset={8}
                onOpenAutoFocus={event => {
                  event.preventDefault();
                  nameInputRef.current?.focus();
                }}
              >
                <div className={styles.addTitle}>
                  <span>添加{marketId === 'a-share' ? 'A股' : marketId === 'hk-share' ? '港股' : '美股'}</span>
                  <Popover.Close aria-label="关闭添加股票" className={styles.closeButton} disabled={mutating}>
                    <X size={16} />
                  </Popover.Close>
                </div>
                {marketId === 'a-share' ? (
                  <AShareStockSearch
                    inputRef={nameInputRef}
                    stocks={stocks}
                    disabled={disabled}
                    onAdd={async stock => {
                      if (await addStock(stock)) setAddOpen(false);
                    }}
                  />
                ) : (
                  <form onSubmit={handleAdd}>
                    <label>
                      股票名称
                      <input
                        ref={nameInputRef}
                        autoComplete="off"
                        disabled={mutating}
                        maxLength={100}
                        onChange={event => setName(event.target.value)}
                        placeholder={marketId === 'hk-share' ? '如 腾讯控股' : '如 苹果'}
                        required
                        value={name}
                      />
                    </label>
                    <label>
                      股票代码
                      <input
                        autoComplete="off"
                        disabled={mutating}
                        maxLength={32}
                        onChange={event => setSymbol(event.target.value)}
                        placeholder={marketId === 'hk-share' ? '如 00700.HK 或 700' : '如 AAPL'}
                        required
                        value={symbol}
                      />
                    </label>
                    {addError && (
                      <p className={styles.formError} role="alert">
                        {addError}
                      </p>
                    )}
                    <button
                      className={styles.submitButton}
                      disabled={disabled || !symbol.trim() || !name.trim()}
                      type="submit"
                    >
                      {mutating && <Loader2 className="dashboard-spin" size={14} />}
                      {mutating ? '添加中' : '添加股票'}
                    </button>
                  </form>
                )}
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
      </div>

      {actionError && (
        <div className={styles.actionError} role="alert">
          {actionError}
        </div>
      )}
      {error && (
        <div className={styles.actionError} role="alert">
          {error}
        </div>
      )}
      {loading && !stocks.length ? (
        <div className={styles.listState}>
          <Loader2 className="dashboard-spin" size={20} />
          <span>正在读取股票列表</span>
        </div>
      ) : stocks.length ? (
        <div aria-label="股票" className={styles.stockList}>
          <AgGridProvider modules={modules}>
            <AgGridReact
              ref={gridRef}
              theme={theme}
              rowData={stocks}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              context={context}
              getRowId={getRowId}
              headerHeight={0}
              rowHeight={45}
              rowSelection={rowSelection}
              rowDragManaged
              rowDragEntireRow
              suppressMoveWhenRowDragging
              suppressRowDrag={disabled}
              dragAndDropImageComponent={StockDragPreview}
              rowDragText={({ rowNode }) => `${rowNode.data.name} · ${rowNode.data.symbol}`}
              onRowDragEnd={handleDragEnd}
              onRowClicked={({ data }) => setSelectedStock(data)}
              onCellKeyDown={({ event, data }) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelectedStock(data);
                }
              }}
              onFirstDataRendered={({ api }) => syncSelection(api)}
              onRowDataUpdated={({ api }) => syncSelection(api)}
              suppressHorizontalScroll
              animateRows
            />
          </AgGridProvider>
        </div>
      ) : (
        <div className={styles.listState}>
          {error || (groupId ? '暂无股票，点击上方添加股票' : '暂无自选分组，请在上方新建分组')}
        </div>
      )}
    </>
  );
}
