import { HoverCard } from 'radix-ui';

import StatusBadge from '@/components/StatusBadge.jsx';
import { shortTime, statusLabel } from '@/utils/formatters.js';
import styles from './DataSourcesView.module.css';

export default function TaskStatusCell({ data }) {
  const status = data.isRunning ? 'running' : data.result?.status || 'idle';
  // 新一轮执行时，旧结果不能作为当前运行的信息展示。
  const result = data.isRunning && data.result?.status !== 'running' ? {} : data.result || {};
  const message =
    result.message ||
    {
      idle: '尚未执行任务。',
      running: '任务正在执行，请稍候…',
      success: '任务执行完成。',
      failed: '任务执行失败，暂无错误详情。'
    }[status];

  return (
    <HoverCard.Root openDelay={150} closeDelay={200}>
      <HoverCard.Trigger asChild>
        <button
          type="button"
          className={styles.statusTrigger}
          aria-label={`${data.name}：${statusLabel(status)}，查看运行详情`}
        >
          <StatusBadge status={status} />
        </button>
      </HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content
          className={`${styles.statusPopover} app-scrollbar`}
          side="right"
          align="center"
          sideOffset={8}
          collisionPadding={12}
          role="region"
          aria-label={`${data.name}运行信息`}
        >
          <h4>{data.name}</h4>
          <dl className={styles.runMetadata}>
            <div>
              <dt>执行状态</dt>
              <dd>{statusLabel(status)}</dd>
            </div>
            <div>
              <dt>运行方式</dt>
              <dd>{data.scheduleText}</dd>
            </div>
            {result.started_at && (
              <div>
                <dt>开始时间</dt>
                <dd>{shortTime(result.started_at).slice(0, 19)}</dd>
              </div>
            )}
            {result.finished_at && (
              <div>
                <dt>结束时间</dt>
                <dd>{shortTime(result.finished_at).slice(0, 19)}</dd>
              </div>
            )}
            {result.duration_seconds != null && (
              <div>
                <dt>运行耗时</dt>
                <dd>{result.duration_seconds} 秒</dd>
              </div>
            )}
          </dl>
          <div className={styles.runDetails}>
            <h5>{status === 'failed' ? '错误信息' : '运行信息'}</h5>
            <p className={status === 'failed' ? styles.runError : undefined}>{message}</p>
          </div>
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}
