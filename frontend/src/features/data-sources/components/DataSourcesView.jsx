import { Database, Loader2, Play } from 'lucide-react';

import StatusBadge from '@/components/StatusBadge.jsx';
import { Button } from '@/shadcn/components/ui/button.jsx';
import { shortTime } from '@/utils/formatters.js';
import styles from './DataSourcesView.module.css';

function latestDataText(taskId, latestUpdateTimes, latestDataStatus) {
  if (latestDataStatus === 'loading') return '读取中…';
  if (latestDataStatus === 'failed') return '读取失败';
  return latestUpdateTimes[taskId] ? shortTime(latestUpdateTimes[taskId]).slice(0, 19) : '暂无数据';
}

export default function DataSourcesView({
  tasks,
  results,
  latestUpdateTimes,
  latestDataStatus,
  runningTaskId,
  error,
  runSync
}) {
  return (
    <div className="dashboard-content">
      <section className="dashboard-panel">
        <div className="dashboard-panel-header">
          <div>
            <h2>数据库脚本同步</h2>
            <span>点击任务按钮调用后端接口；同一时间只执行一个写入任务</span>
          </div>
          <Database size={19} />
        </div>

        <div className={styles.grid}>
          {tasks.map(task => {
            const result = results[task.id];
            const isRunning = result.status === 'running';
            const isDisabled = Boolean(runningTaskId);

            return (
              <article key={task.id} className={styles.card}>
                <div className={styles.cardHead}>
                  <div>
                    <h3>{task.name}</h3>
                  </div>
                  <StatusBadge status={result.status} />
                </div>

                <p className={styles.description}>{task.description}</p>

                <dl>
                  {(task.latestDataFields || [{ id: task.id, label: '最新数据' }]).map(field => (
                    <div key={field.id}>
                      <dt>{field.label}</dt>
                      <dd>{latestDataText(field.id, latestUpdateTimes, latestDataStatus)}</dd>
                    </div>
                  ))}
                  <div>
                    <dt>最近执行</dt>
                    <dd>{shortTime(result.finishedAt)}</dd>
                  </div>
                </dl>

                {result.message ? (
                  <div className={`${styles.result} ${styles[result.status] || ''}`}>
                    {result.message}
                    {result.duration !== null ? `，耗时 ${result.duration} 秒` : ''}
                  </div>
                ) : null}

                <Button
                  className={styles.runButton}
                  type="button"
                  onClick={() => runSync(task.id)}
                  disabled={isDisabled}
                >
                  {isRunning ? <Loader2 className="dashboard-spin" size={15} /> : <Play size={15} />}
                  <span>{isRunning ? '执行中…' : '执行同步'}</span>
                </Button>
              </article>
            );
          })}
        </div>
      </section>

      {error ? <div className="dashboard-notice">{error}</div> : null}
    </div>
  );
}
