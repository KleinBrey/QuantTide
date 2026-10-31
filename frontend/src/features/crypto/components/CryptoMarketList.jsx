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
import { Plus, RefreshCcw, X } from 'lucide-react';
import { ContextMenu, Popover } from 'radix-ui';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/shadcn/components/ui/select.jsx';
import sharedStyles from '@/components/watchlist/MarketBrowser.module.css';
import styles from './CryptoMarketBrowser.module.css';

const QUOTE_ASSETS = ['USDT', 'USDC', 'FDUSD', 'TUSD', 'DAI', 'BTC', 'ETH', 'BNB', 'EUR', 'TRY'];

function PairName({ symbol }) {
  // 只拆分显示名称，请求、分组和排序仍使用原始交易对代码。
  const quote = QUOTE_ASSETS.find(asset => symbol.length > asset.length && symbol.endsWith(asset));
  const base = quote ? symbol.slice(0, -quote.length) : symbol;

  return (
    <span className={styles.pairName}>
      <strong>{base}</strong>
      {quote && <span className={styles.quoteAsset}> /{quote}</span>}
    </span>
  );
}

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
const columnDefs = [{ headerName: '交易对', field: 'symbol', flex: 1, cellRenderer: CryptoCell }];
const defaultColDef = { sortable: false, resizable: false, suppressMovable: true };
const rowSelection = { mode: 'singleRow', checkboxes: false, enableClickSelection: 'enableSelection' };
const getRowId = params => params.data.symbol;

function CryptoDragPreview({ dragSource }) {
  const rowNode = dragSource.getDragItem().rowNode;
  const pairRow = dragSource.eElement.querySelector('[data-crypto-row]') ?? dragSource.eElement;
  const { width, height } = pairRow.getBoundingClientRect();
  const { fontFamily, lineHeight } = window.getComputedStyle(dragSource.eElement);
  const selected = rowNode.isSelected();

  return (
    <div
      className={`${sharedStyles.stockDragPreview}${selected ? ` ${sharedStyles.stockDragPreviewSelected}` : ''}`}
      style={{ width, height, fontFamily, lineHeight }}
      aria-hidden="true"
    >
      <div className={sharedStyles.stockItem}>
        <PairName symbol={rowNode.data.symbol} />
        <small>现货</small>
      </div>
    </div>
  );
}

function CryptoCell({ data: item, context }) {
  const { symbols, groups, groupId, addToGroup, removeSymbol, reorderSymbols, disabled } = context;
  const index = symbols.findIndex(row => row.symbol === item.symbol);
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild disabled={disabled}>
        <div data-crypto-row className={sharedStyles.stockItem} title={item.symbol}>
          <PairName symbol={item.symbol} />
          <small>现货</small>
        </div>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className={sharedStyles.contextMenu}>
          <ContextMenu.Sub>
            <ContextMenu.SubTrigger className={sharedStyles.menuItem} disabled={disabled}>
              加入分组
            </ContextMenu.SubTrigger>
            <ContextMenu.Portal>
              <ContextMenu.SubContent className={sharedStyles.contextMenu}>
                {groups
                  .filter(group => group.id !== groupId)
                  .map(group => (
                    <ContextMenu.Item
                      key={group.id}
                      className={sharedStyles.menuItem}
                      onSelect={() => addToGroup(group.id, item.symbol)}
                    >
                      {group.name}
                    </ContextMenu.Item>
                  ))}
                {groups.length < 2 && (
                  <ContextMenu.Item disabled className={sharedStyles.menuItem}>
                    请先新建分组
                  </ContextMenu.Item>
                )}
              </ContextMenu.SubContent>
            </ContextMenu.Portal>
          </ContextMenu.Sub>
          <ContextMenu.Item
            className={sharedStyles.menuItem}
            disabled={disabled || index === 0}
            onSelect={() => reorderSymbols([item, ...symbols.filter(row => row.id !== item.id)])}
          >
            移到最前
          </ContextMenu.Item>
          <ContextMenu.Item
            className={sharedStyles.menuItem}
            disabled={disabled || index === symbols.length - 1}
            onSelect={() => reorderSymbols([...symbols.filter(row => row.id !== item.id), item])}
          >
            移到最后
          </ContextMenu.Item>
          <ContextMenu.Separator className={sharedStyles.menuSeparator} />
          <ContextMenu.Item className={sharedStyles.menuItem} disabled={disabled} onSelect={() => removeSymbol(item)}>
            移出当前分组
          </ContextMenu.Item>
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}

export default function CryptoMarketList({
  symbols,
  selected,
  setSelected,
  loading,
  syncing,
  error,
  sync,
  syncGroup,
  groups,
  groupId,
  addToGroup,
  removeSymbol,
  reorderSymbols
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [input, setInput] = useState('');
  const [quoteAsset, setQuoteAsset] = useState('USDT');
  const inputRef = useRef(null);
  const gridRef = useRef(null);
  const disabled = loading || syncing;
  const context = useMemo(
    () => ({ symbols, groups, groupId, addToGroup, removeSymbol, reorderSymbols, disabled }),
    [symbols, groups, groupId, addToGroup, removeSymbol, reorderSymbols, disabled]
  );

  const syncSelection = api => {
    if (selected) api.getRowNode(selected)?.setSelected(true);
  };

  useEffect(() => {
    const api = gridRef.current?.api;
    if (api && !api.isDestroyed()) api.refreshCells({ force: true });
  }, [context]);

  useEffect(() => {
    const api = gridRef.current?.api;
    if (!api || api.isDestroyed()) return;
    const node = api.getRowNode(selected);
    if (node) {
      node.setSelected(true);
      api.ensureNodeVisible(node);
    }
  }, [selected]);

  const handleDragEnd = ({ api }) => {
    // 与股票列表一致：等表格完成行移动后，再读取并保存最终顺序。
    queueMicrotask(() => {
      if (api.isDestroyed()) return;
      const ordered = [];
      api.forEachNodeAfterFilterAndSort(node => ordered.push(node.data));
      if (ordered.length === symbols.length) reorderSymbols(ordered);
    });
  };

  async function handleAdd(event) {
    event.preventDefault();
    const symbol = `${input.trim().toUpperCase()}${quoteAsset}`;
    if (await sync(symbol, true)) {
      setInput('');
      setQuoteAsset('USDT');
      setAddOpen(false);
    }
  }

  return (
    <>
      <div className={styles.listHeader}>
        <span>交易对 / 代码</span>
        <div className={styles.listActions} aria-busy={syncing}>
          <strong>{symbols.length}</strong>
          <button
            className={styles.iconButton}
            type="button"
            aria-label="获取当前分组的最新日 K 线"
            title="获取当前分组的最新日 K 线"
            disabled={disabled || !groupId || !symbols.length}
            onClick={syncGroup}
          >
            <RefreshCcw size={14} className={syncing ? styles.spinning : ''} />
          </button>
          <Popover.Root
            open={addOpen}
            onOpenChange={open => {
              if (!syncing) setAddOpen(open);
            }}
          >
            <Popover.Trigger asChild>
              <button className={styles.addButton} type="button" disabled={syncing || loading || !groupId}>
                <Plus size={14} />
                添加交易对
              </button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                className={styles.addPopover}
                aria-label="添加交易对"
                align="start"
                sideOffset={8}
                collisionPadding={8}
                onInteractOutside={event => {
                  // 下拉菜单通过 Portal 显示，选择选项时保留外层添加弹窗。
                  if (event.target.closest('[data-slot="select-content"]')) event.preventDefault();
                }}
                onOpenAutoFocus={event => {
                  event.preventDefault();
                  inputRef.current?.focus();
                }}
              >
                <div className={styles.addTitle}>
                  <span>添加交易对</span>
                  <Popover.Close className={styles.iconButton} aria-label="关闭添加交易对" disabled={syncing}>
                    <X size={16} />
                  </Popover.Close>
                </div>
                <form onSubmit={handleAdd}>
                  <label>
                    名称
                    <input
                      ref={inputRef}
                      placeholder="如 BTC、ETH"
                      value={input}
                      onChange={event => setInput(event.target.value.toUpperCase())}
                      required
                      pattern="[A-Za-z0-9]+"
                      maxLength={30 - quoteAsset.length}
                      disabled={syncing}
                      autoComplete="off"
                    />
                  </label>
                  <div className={styles.quoteField}>
                    <span id="crypto-quote-label">计价币</span>
                    <Select
                      value={quoteAsset}
                      onValueChange={setQuoteAsset}
                      disabled={syncing}
                      modal={false}
                      items={QUOTE_ASSETS.map(asset => ({ value: asset, label: asset }))}
                    >
                      <SelectTrigger aria-labelledby="crypto-quote-label">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent alignItemWithTrigger={false}>
                        <SelectGroup>
                          {QUOTE_ASSETS.map(asset => (
                            <SelectItem key={asset} value={asset}>
                              {asset}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </div>
                  <p className={styles.formHint}>没有本地行情时同步最近一年的日 K。</p>
                  {error && (
                    <p className={styles.error} role="alert">
                      {error}
                    </p>
                  )}
                  <button className={styles.submitButton} type="submit" disabled={syncing || !input.trim()}>
                    {syncing ? '正在同步…' : '添加并同步'}
                  </button>
                </form>
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
      </div>
      {error && !addOpen && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {symbols.length ? (
        <div aria-label="交易对" className={sharedStyles.stockList}>
          <AgGridProvider modules={modules}>
            <AgGridReact
              ref={gridRef}
              theme={theme}
              rowData={symbols}
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
              dragAndDropImageComponent={CryptoDragPreview}
              rowDragText={({ rowNode }) => rowNode.data.symbol}
              onRowDragEnd={handleDragEnd}
              onRowClicked={({ data }) => setSelected(data.symbol)}
              onCellKeyDown={({ event, data }) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  setSelected(data.symbol);
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
        <div className={styles.listState}>{loading ? '正在读取交易对…' : '暂无交易对，点击上方添加交易对'}</div>
      )}
    </>
  );
}
