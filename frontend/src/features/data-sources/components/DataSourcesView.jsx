import { useMemo, useRef, useState } from 'react';
import {
  CellStyleModule,
  ClientSideRowModelApiModule,
  ClientSideRowModelModule,
  RowDragModule,
  colorSchemeDark,
  themeQuartz
} from 'ag-grid-community';
import { AgGridProvider, AgGridReact } from 'ag-grid-react';
import { Loader2, Pencil, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/shadcn/components/ui/button.jsx';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/shadcn/components/ui/dialog.jsx';
import { shortTime } from '@/utils/formatters.js';
import { useDataSources } from '../hooks/useDataSources.js';
import TaskEditor from './TaskEditor.jsx';
import TaskStatusCell from './TaskStatusCell.jsx';
import { formatTaskCron } from '../utils/taskSchedule.js';
import styles from './DataSourcesView.module.css';

const modules = [ClientSideRowModelModule, ClientSideRowModelApiModule, CellStyleModule, RowDragModule];
const taskGridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: 'var(--card)',
  foregroundColor: 'var(--foreground)',
  borderColor: 'var(--border)',
  rowHoverColor: 'var(--accent)',
  rowDragIndicatorColor: '#71717a',
  fontFamily: 'inherit',
  fontSize: 13,
  cellHorizontalPadding: 6,
  columnBorder: false,
  wrapperBorder: false,
  wrapperBorderRadius: 0
});
const defaultColDef = { sortable: false, resizable: false, suppressMovable: true, cellClass: styles.cell };

function TaskLoadingOverlay() {
  return (
    <div
      className="flex items-center gap-2 rounded-md border border-border bg-card px-4 py-3 text-sm text-foreground shadow-sm"
      role="status"
    >
      <Loader2 className="dashboard-spin" size={16} />
      正在读取任务…
    </div>
  );
}

function TaskNameCell({ data }) {
  return (
    <div className={styles.taskName}>
      <h3 title={data.name}>{data.name}</h3>
      <p className={styles.description} title={data.description}>
        {data.description}
      </p>
    </div>
  );
}

function TaskMarketsCell({ data }) {
  return (
    <div className={styles.markets} aria-label="适用市场">
      {data.markets.length
        ? data.markets.map(market => (
            <span key={market} className={styles.marketBadge} data-market={market}>
              {market}
            </span>
          ))
        : '—'}
    </div>
  );
}

function TaskScheduleCell({ data }) {
  return (
    <dl className={styles.metadata}>
      <div>
        <dt>运行方式</dt>
        <dd title={data.scheduleText}>{data.scheduleText}</dd>
      </div>
      {data.showNextRun && (
        <div>
          <dt>下次执行</dt>
          <dd>{data.nextRunText}</dd>
        </div>
      )}
      <div>
        <dt>最近执行</dt>
        <dd>{data.lastRunText}</dd>
      </div>
    </dl>
  );
}

function TaskLatestDataCell({ data }) {
  return (
    <dl className={styles.metadata}>
      {data.latestFields.map(field => (
        <div key={field.id}>
          <dt>{field.label}</dt>
          <dd>{field.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function TaskActionsCell({ data, context }) {
  return (
    <div className={styles.taskActions}>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label={`编辑${data.name}`}
        onClick={() => context.editTask(data)}
        disabled={data.isRunning || data.isDeleting}
      >
        <Pencil size={14} />
        编辑
      </Button>
      {data.schedule ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => context.toggleTask(data)}
          disabled={data.isRunning || data.isDeleting}
        >
          {data.enabled ? '停用调度' : '启用调度'}
        </Button>
      ) : (
        <span className={styles.scheduleActionPlaceholder} />
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label={`删除${data.name}`}
        onClick={() => context.confirmDelete(data)}
        disabled={data.isRunning || context.deletingId !== null || context.reordering}
      >
        <Trash2 size={14} />
        删除
      </Button>
      <Button
        className={styles.runButton}
        type="button"
        size="sm"
        aria-label={`立即执行${data.name}`}
        onClick={() => context.runTask(data.id)}
        disabled={context.runningTaskId !== null || data.isDeleting}
      >
        {data.isRunning ? <Loader2 className="dashboard-spin" size={15} /> : <Play size={15} />}
        <span>{data.isRunning ? '执行中…' : '立即执行'}</span>
      </Button>
    </div>
  );
}

const columnDefs = [
  { colId: 'order', headerName: '排序', width: 40, minWidth: 40, rowDrag: true },
  { field: 'name', headerName: '任务', width: 150, minWidth: 150, cellRenderer: TaskNameCell },
  { field: 'markets', headerName: '市场', width: 84, minWidth: 84, cellRenderer: TaskMarketsCell },
  { colId: 'status', headerName: '状态', width: 120, minWidth: 120, cellRenderer: TaskStatusCell },
  { colId: 'schedule', headerName: '调度时间', minWidth: 200, flex: 1, cellRenderer: TaskScheduleCell },
  { colId: 'latest', headerName: '数据更新时间', minWidth: 200, flex: 1, cellRenderer: TaskLatestDataCell },
  { colId: 'actions', headerName: '操作', width: 380, cellRenderer: TaskActionsCell }
];

const TASK_MARKETS = {
  realtime_hot: ['A 股', '港股', '美股'],
  daily_stocks: ['A 股'],
  daily_basic: ['A 股'],
  daily_bars: ['A 股'],
  daily_hot: ['A 股'],
  hk_daily_bars: ['港股'],
  us_daily_bars: ['美股'],
  futures_market: ['期货'],
  crypto_daily_bars: ['加密货币']
};

const LATEST_FIELDS = {
  futures_market: [{ id: 'futures-daily-k', label: '最新数据' }],
  daily_bars: [{ id: 'daily-k', label: '最新数据' }],
  daily_basic: [{ id: 'stock-daily-basic', label: '最新数据' }],
  daily_stocks: [{ id: 'stock-list', label: '最新数据' }],
  realtime_hot: [
    { id: 'hot-stock', label: 'A 股热度' },
    { id: 'hk-hot-stock', label: '港股热度' },
    { id: 'us-hot-stock', label: '美股热度' }
  ],
  daily_hot: [{ id: 'hot-stock', label: 'A 股热度' }],
  hk_daily_bars: [{ id: 'hk-daily-k', label: '最新数据' }],
  us_daily_bars: [{ id: 'us-daily-k', label: '最新数据' }],
  crypto_daily_bars: [{ id: 'crypto-daily-k', label: '最新数据' }]
};

function latestDataText(taskId, latestUpdateTimes, latestDataStatus) {
  if (latestDataStatus === 'loading') return '读取中…';
  if (latestDataStatus === 'failed') return '读取失败';
  return latestUpdateTimes[taskId] ? shortTime(latestUpdateTimes[taskId]).slice(0, 19) : '暂无数据';
}

function scheduleText(task) {
  if (!task.schedule) return '仅手动运行';
  const rule = task.schedule.trigger === 'cron' ? formatTaskCron(task.schedule.cron) : `每 ${task.schedule.seconds / 3600} 小时`;
  return `${rule}${task.enabled ? '' : ' · 已停用'}`;
}

export default function DataSourcesView() {
  const {
    tasks,
    scripts,
    settings,
    latestUpdateTimes,
    latestDataStatus,
    loading,
    reordering,
    runningTaskId,
    runTask,
    reload,
    saveTask,
    removeTask,
    toggleTask,
    reorderTasks
  } = useDataSources();
  const [editor, setEditor] = useState(null);
  const [taskToDelete, setTaskToDelete] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [localError, setLocalError] = useState('');
  const cancelDeleteButton = useRef(null);
  const draggingTask = useRef(false);
  const rowData = useMemo(
    () =>
      tasks.map(task => {
        return {
          ...task,
          description: `${task.params?.lookback_days ? `最近 ${task.params.lookback_days} 个自然日` : ''}`,
          markets: TASK_MARKETS[task.script_id] || [],
          isRunning: task.id === runningTaskId || task.result?.status === 'running',
          isDeleting: task.id === deletingId,
          scheduleText: scheduleText(task),
          showNextRun: Boolean(task.schedule && settings.scheduler_enabled && task.enabled),
          nextRunText: task.next_run_at ? shortTime(task.next_run_at).slice(0, 19) : '待调度',
          lastRunText: task.result?.finished_at ? shortTime(task.result.finished_at).slice(0, 19) : '尚未执行',
          latestFields: (LATEST_FIELDS[task.script_id] || []).map(field => ({
            ...field,
            value: latestDataText(field.id, latestUpdateTimes, latestDataStatus)
          }))
        };
      }),
    [tasks, runningTaskId, deletingId, settings.scheduler_enabled, latestUpdateTimes, latestDataStatus]
  );

  function confirmDelete(task) {
    setLocalError('');
    setTaskToDelete(task);
  }

  async function finishTaskDrag({ api }) {
    if (!draggingTask.current) return;
    draggingTask.current = false;
    const ids = [];
    api.forEachNodeAfterFilterAndSort(node => ids.push(node.data.id));
    try {
      await reorderTasks(ids);
    } catch (err) {
      api.setGridOption('rowData', [...rowData]);
      toast.error(`任务顺序保存失败：${err.message || '请稍后重试'}`);
    }
  }

  async function deleteTask() {
    if (!taskToDelete || deletingId !== null) return;
    const task = taskToDelete;
    setDeletingId(task.id);
    setLocalError('');
    try {
      await removeTask(task.id);
      setTaskToDelete(null);
    } catch (err) {
      setLocalError(err.message || '删除任务失败');
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className={`dashboard-content ${styles.content}`}>
      <section className={`dashboard-panel ${styles.panel}`}>
        <div className={`dashboard-panel-header ${styles.panelHeader}`}>
          <div>
            <h2>任务列表</h2>
            <span>管理同步任务和运行时间；同一时间只执行一个写入任务</span>
          </div>
          <div className={styles.headerActions}>
            <Button
              type="button"
              variant="outline"
              onClick={reload}
              disabled={loading || reordering}
              aria-label="刷新任务列表"
            >
              <RefreshCw size={15} />
              刷新
            </Button>
            <Button type="button" onClick={() => setEditor({ task: null })} disabled={!scripts.length || reordering}>
              <Plus size={15} />
              新增任务
            </Button>
          </div>
        </div>
        {reordering && (
          <p className={styles.orderStatus} role="status">
            正在保存任务顺序…
          </p>
        )}
        {!settings.scheduler_enabled && (
          <p className={styles.helpBanner}>服务当前未启用自动调度，定时配置已保存，仍可手动执行任务。</p>
        )}
        <div className={styles.grid} aria-label="同步任务列表" aria-busy={loading}>
          <AgGridProvider modules={modules}>
            <AgGridReact
              theme={taskGridTheme}
              rowData={rowData}
              loading={loading}
              loadingOverlayComponent={TaskLoadingOverlay}
              overlayNoRowsTemplate='<span class="ag-overlay-no-rows-center">暂无任务，点击“新增任务”添加。</span>'
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              context={{
                editTask: task => setEditor({ task }),
                toggleTask,
                confirmDelete,
                runTask,
                runningTaskId,
                deletingId,
                reordering
              }}
              getRowId={params => String(params.data.id)}
              headerHeight={0}
              rowHeight={116}
              rowDragManaged
              suppressMoveWhenRowDragging
              rowDragText={params => params.rowNode.data.name}
              suppressRowDrag={loading || reordering || deletingId !== null}
              onRowDragEnter={() => {
                draggingTask.current = true;
              }}
              onDragStopped={finishTaskDrag}
              onDragCancelled={({ api }) => {
                draggingTask.current = false;
                api.setGridOption('rowData', [...rowData]);
              }}
              domLayout="normal"
              suppressCellFocus
              enableCellTextSelection
              animateRows
              suppressScrollOnNewData
            />
          </AgGridProvider>
        </div>
      </section>
      {editor && (
        <TaskEditor
          task={editor.task}
          scripts={scripts}
          settings={settings}
          onSave={saveTask}
          onClose={() => setEditor(null)}
        />
      )}
      <Dialog
        open={Boolean(taskToDelete)}
        disablePointerDismissal={deletingId !== null}
        onOpenChange={(open, details) => {
          if (open) return;
          if (deletingId !== null) details.cancel();
          else setTaskToDelete(null);
        }}
      >
        <DialogContent showCloseButton={false} initialFocus={cancelDeleteButton} className="bg-card">
          <DialogHeader>
            <DialogTitle>删除任务</DialogTitle>
            <DialogDescription className="break-words">
              删除任务“{taskToDelete?.name}”？已同步的数据会保留。
            </DialogDescription>
          </DialogHeader>
          {localError && (
            <p className={styles.formError} role="alert">
              {localError}
            </p>
          )}
          <DialogFooter>
            <DialogClose
              render={
                <Button ref={cancelDeleteButton} type="button" variant="outline" disabled={deletingId !== null} />
              }
              disabled={deletingId !== null}
            >
              取消
            </DialogClose>
            <Button type="button" variant="destructive" onClick={deleteTask} disabled={deletingId !== null}>
              {deletingId !== null && <Loader2 className="dashboard-spin" size={15} />}
              {deletingId !== null ? '删除中…' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
