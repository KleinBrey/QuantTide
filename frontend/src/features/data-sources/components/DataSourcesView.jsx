import { useState } from 'react';
import { Loader2, Pencil, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';

import StatusBadge from '@/components/StatusBadge.jsx';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { shortTime } from '@/utils/formatters.js';
import TaskEditor from './TaskEditor.jsx';
import styles from './DataSourcesView.module.css';

const LATEST_FIELDS = {
  daily_bars: [{ id: 'daily-k', label: '最新数据' }],
  daily_basic: [{ id: 'stock-daily-basic', label: '最新数据' }],
  daily_stocks: [{ id: 'stock-list', label: '最新数据' }],
  daily_hot: [{ id: 'hot-stock', label: 'A 股热度' }, { id: 'hk-hot-stock', label: '港股热度' }, { id: 'us-hot-stock', label: '美股热度' }],
  cn_daily_hot: [{ id: 'hot-stock', label: 'A 股热度' }],
  hk_us_daily_bars: [{ id: 'hk-daily-k', label: '港股数据' }, { id: 'us-daily-k', label: '美股数据' }]
};

function latestDataText(taskId, latestUpdateTimes, latestDataStatus) {
  if (latestDataStatus === 'loading') return '读取中…';
  if (latestDataStatus === 'failed') return '读取失败';
  return latestUpdateTimes[taskId] ? shortTime(latestUpdateTimes[taskId]).slice(0, 19) : '暂无数据';
}

function scheduleText(task) {
  if (!task.schedule) return '仅手动运行';
  const rule = task.schedule.trigger === 'cron' ? task.schedule.cron : `每 ${task.schedule.seconds} 秒`;
  return `${rule}${task.enabled ? '' : ' · 已停用'}`;
}

export default function DataSourcesView({
  tasks, scripts, settings, latestUpdateTimes, latestDataStatus, loading,
  runningTaskId, error, runTask, reload, saveTask, removeTask, toggleTask
}) {
  const [editor, setEditor] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [localError, setLocalError] = useState('');

  async function confirmDelete(task) {
    if (!window.confirm(`删除任务“${task.name}”？已同步的数据会保留。`)) return;
    setDeletingId(task.id);
    setLocalError('');
    try {
      await removeTask(task.id);
    } catch (err) {
      setLocalError(err.message || '删除任务失败');
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="dashboard-content">
      <section className="dashboard-panel">
        <div className="dashboard-panel-header">
          <div>
            <h2>任务列表</h2>
            <span>管理同步任务和运行时间；同一时间只执行一个写入任务</span>
          </div>
          <div className={styles.headerActions}>
            <Button type="button" variant="outline" onClick={reload} disabled={loading} aria-label="刷新任务列表">
              <RefreshCw size={15} />刷新
            </Button>
            <Button type="button" onClick={() => setEditor({ task: null })} disabled={!scripts.length}>
              <Plus size={15} />新增任务
            </Button>
          </div>
        </div>
        {!settings.scheduler_enabled && <p className={styles.helpBanner}>服务当前未启用自动调度，定时配置已保存，仍可手动执行任务。</p>}
        {loading && <p className={styles.empty}>正在读取任务…</p>}
        {!loading && tasks.length === 0 && <div className={styles.empty}>暂无任务，点击“新增任务”添加。</div>}
        {!loading && tasks.length > 0 && (
          <div className={styles.grid}>
            {tasks.map(task => {
              const result = task.result || { status: 'idle' };
              const isRunning = task.id === runningTaskId || result.status === 'running';
              const script = scripts.find(item => item.id === task.script_id);
              const showNextRun = task.schedule && settings.scheduler_enabled && task.enabled;
              const fields = LATEST_FIELDS[task.script_id] || [];
              return (
                <article key={task.id} className={styles.card}>
                  <div className={styles.cardHead}>
                    <h3>{task.name}</h3>
                    <StatusBadge status={isRunning ? 'running' : result.status} />
                  </div>
                  <p className={styles.description}>
                    {script?.name || task.script_id}
                    {task.params.lookback_days ? ` · 最近 ${task.params.lookback_days} 个自然日` : ''}
                  </p>
                  <dl>
                    <div>
                      <dt>运行方式</dt>
                      <dd title={scheduleText(task)}>{scheduleText(task)}</dd>
                    </div>
                    {showNextRun && (
                      <div>
                        <dt>下次执行</dt>
                        <dd>{task.next_run_at ? shortTime(task.next_run_at).slice(0, 19) : '待调度'}</dd>
                      </div>
                    )}
                    {fields.map(field => (
                      <div key={field.id}>
                        <dt>{field.label}</dt>
                        <dd>{latestDataText(field.id, latestUpdateTimes, latestDataStatus)}</dd>
                      </div>
                    ))}
                    <div>
                      <dt>最近执行</dt>
                      <dd>{result.finished_at ? shortTime(result.finished_at).slice(0, 19) : '尚未执行'}</dd>
                    </div>
                  </dl>
                  {result.message && (
                    <div className={`${styles.result} ${styles[result.status] || ''}`}>
                      {result.message}{result.duration_seconds != null ? `，耗时 ${result.duration_seconds} 秒` : ''}
                    </div>
                  )}
                  <div className={styles.taskActions}>
                    <Button type="button" variant="outline" size="sm"
                      onClick={() => setEditor({ task })} disabled={isRunning || deletingId === task.id}>
                      <Pencil size={14} />编辑
                    </Button>
                    {task.schedule && (
                      <Button type="button" variant="outline" size="sm"
                        onClick={() => toggleTask(task)} disabled={isRunning || deletingId === task.id}>
                        {task.enabled ? '停用调度' : '启用调度'}
                      </Button>
                    )}
                    <Button type="button" variant="ghost" size="sm" aria-label={`删除${task.name}`}
                      onClick={() => confirmDelete(task)} disabled={isRunning || deletingId !== null}>
                      <Trash2 size={14} />删除
                    </Button>
                  </div>
                  <Button className={styles.runButton} type="button"
                    onClick={() => runTask(task.id)} disabled={runningTaskId !== null || deletingId === task.id}>
                    {isRunning ? <Loader2 className="dashboard-spin" size={15} /> : <Play size={15} />}
                    <span>{isRunning ? '执行中…' : '立即执行'}</span>
                  </Button>
                </article>
              );
            })}
          </div>
        )}
      </section>
      {(error || localError) && <div className="dashboard-notice" role="alert">{localError || error}</div>}
      {editor && <TaskEditor task={editor.task} scripts={scripts} settings={settings} onSave={saveTask} onClose={() => setEditor(null)} />}
    </div>
  );
}
