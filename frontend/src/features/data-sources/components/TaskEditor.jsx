import { useState } from 'react';
import { X } from 'lucide-react';

import { Button } from '@/shadcn/components/ui/button.jsx';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shadcn/components/ui/dialog.jsx';
import { Input } from '@/shadcn/components/ui/input.jsx';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/shadcn/components/ui/select.jsx';
import { buildTaskCron, parseTaskCron, SCHEDULE_PERIODS, WEEKDAYS } from '../utils/taskSchedule.js';
import styles from './DataSourcesView.module.css';

const RUN_MODES = [
  { value: 'manual', label: '仅手动运行' },
  { value: 'cron', label: '按时间定时运行' },
  { value: 'interval', label: '按固定间隔运行' }
];

const MONTH_DAYS = Array.from({ length: 31 }, (_, index) => ({ value: String(index + 1), label: `${index + 1} 日` }));

export default function TaskEditor({ task, scripts, settings, onSave, onClose }) {
  const [scriptId, setScriptId] = useState(task?.script_id || scripts[0]?.id || '');
  const script = scripts.find(item => item.id === scriptId);
  const [name, setName] = useState(task?.name || script?.name || '');
  const [days, setDays] = useState(task?.params?.lookback_days ?? script?.params.lookback_days ?? 3);
  const [mode, setMode] = useState(task?.schedule?.trigger || 'manual');
  const [cronSchedule, setCronSchedule] = useState(() => parseTaskCron(task?.schedule?.cron));
  const [seconds, setSeconds] = useState(task?.schedule?.seconds || 3600);
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function changeScript(value) {
    const selected = scripts.find(item => item.id === value);
    if (!selected) return;
    if (!name || name === script?.name) setName(selected.name);
    setScriptId(value);
    setDays(selected.params.lookback_days ?? 3);
  }

  async function submit(event) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError('');
    try {
      const params = Object.hasOwn(script.params, 'lookback_days') ? { lookback_days: Number(days) } : {};
      // 手动任务没有定时规则；其余两种方式分别构造对应配置。
      let schedule = null;
      if (mode === 'cron') {
        schedule = { trigger: 'cron', cron: cronSchedule.period === 'custom' ? task.schedule.cron : buildTaskCron(cronSchedule) };
      } else if (mode === 'interval') {
        schedule = { trigger: 'interval', seconds: Number(seconds) };
      }
      await onSave(task?.id, { name: name.trim(), script_id: scriptId, params, schedule, enabled });
      onClose();
    } catch (err) {
      setError(err.message || '保存任务失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open disablePointerDismissal={saving} onOpenChange={(open, details) => {
      if (open) return;
      if (saving) details.cancel();
      else onClose();
    }}>
      <DialogContent showCloseButton={false} initialFocus={false}
        className="flex max-h-[90dvh] w-[520px] flex-col overflow-hidden bg-card sm:max-w-[520px]">
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col gap-5 overflow-hidden">
          <DialogHeader className="shrink-0 flex-row items-center justify-between">
            <div>
              <DialogTitle className="text-xl font-bold">{task ? '编辑任务' : '新增任务'}</DialogTitle>
              <DialogDescription className="sr-only">设置同步任务的名称、执行脚本和运行时间。</DialogDescription>
            </div>
            <DialogClose render={<Button variant="ghost" size="icon" disabled={saving} />} aria-label="关闭" disabled={saving}>
              <X size={18} />
            </DialogClose>
          </DialogHeader>
          <div className={`${styles.editorScroll} app-scrollbar min-h-0 flex-1 [color-scheme:dark]`}>
          <fieldset disabled={saving} className={styles.fields}>
            <label>任务名称</label>
            <Input required maxLength={100} value={name} onChange={event => setName(event.target.value)} />
            <span id="task-script-label" className={styles.fieldLabel}>执行脚本</span>
            {/* 弹窗管理背景隔离，下拉无需再次锁定页面滚动。 */}
            <Select value={scriptId} onValueChange={changeScript} disabled={saving} required modal={false}
              items={scripts.map(item => ({ value: item.id, label: item.name }))}>
              <SelectTrigger aria-labelledby="task-script-label"><SelectValue placeholder="选择执行脚本" /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {scripts.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            {Object.hasOwn(script?.params || {}, 'lookback_days') && <>
              <label>同步最近多少个自然日</label>
              <Input type="number" min="1" step="1" required value={days} onChange={event => setDays(event.target.value)} />
            </>}
            <span id="task-schedule-label" className={styles.fieldLabel}>运行方式</span>
            <Select value={mode} onValueChange={setMode} items={RUN_MODES} disabled={saving} modal={false}>
              <SelectTrigger aria-labelledby="task-schedule-label"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {RUN_MODES.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            {mode === 'cron' && <>
              <fieldset className={styles.schedulePeriod}>
                <legend>执行周期</legend>
                <div className={styles.scheduleOptions}>
                  {SCHEDULE_PERIODS.map(item => <label key={item.value} className={styles.scheduleOption}>
                    <input type="radio" name="task-period" value={item.value} checked={cronSchedule.period === item.value}
                      onChange={() => setCronSchedule(current => ({ ...current, period: item.value }))} />
                    {item.label}
                  </label>)}
                  {parseTaskCron(task?.schedule?.cron).period === 'custom' && <label className={styles.scheduleOption}>
                    <input type="radio" name="task-period" value="custom" checked={cronSchedule.period === 'custom'}
                      onChange={() => setCronSchedule(current => ({ ...current, period: 'custom' }))} />
                    保留原规则
                  </label>}
                </div>
              </fieldset>
              {cronSchedule.period === 'weekly' && <fieldset className={styles.schedulePeriod}>
                <legend>执行星期（可多选）</legend>
                <div className={styles.scheduleOptions}>
                  {WEEKDAYS.map(day => <label key={day.value} className={styles.scheduleOption}>
                    <input type="checkbox" checked={cronSchedule.weekdays.includes(day.value)}
                      onChange={event => setCronSchedule(current => ({ ...current, weekdays: event.target.checked
                        ? [...current.weekdays, day.value] : current.weekdays.filter(value => value !== day.value) }))} />
                    {day.label}
                  </label>)}
                </div>
              </fieldset>}
              {cronSchedule.period === 'monthly' && <>
                <span id="task-month-day-label" className={styles.fieldLabel}>执行日期</span>
                <Select value={cronSchedule.monthDay} onValueChange={value => setCronSchedule(current => ({ ...current, monthDay: value }))}
                  items={MONTH_DAYS} disabled={saving} modal={false}>
                  <SelectTrigger aria-labelledby="task-month-day-label"><SelectValue /></SelectTrigger>
                  <SelectContent alignItemWithTrigger={false}>
                    <SelectGroup>
                      {MONTH_DAYS.map(day => <SelectItem key={day.value} value={day.value}>{day.label}</SelectItem>)}
                    </SelectGroup>
                  </SelectContent>
                </Select>
                {Number(cronSchedule.monthDay) > 28 && <p className={styles.help}>当月没有所选日期时，跳过该月。</p>}
              </>}
              {cronSchedule.period === 'custom' ? <p className={styles.help}>当前任务使用其他定时规则，保存时保留原规则。选择执行周期可重新设置。</p> : <>
                <label>执行时间（24 小时制）</label>
                <Input type="time" lang="en-GB" step="60" required value={cronSchedule.time}
                  onChange={event => setCronSchedule(current => ({ ...current, time: event.target.value }))} aria-describedby="schedule-help" />
              </>}
              <p id="schedule-help" className={styles.help}>{cronSchedule.period === 'workdays' ? '工作日为周一至周五。' : ''}时区：{settings.timezone}。</p>
            </>}
            {mode === 'interval' && <>
              <label>执行间隔（秒）</label>
              <Input type="number" min="1" step="1" required value={seconds} onChange={event => setSeconds(event.target.value)} />
            </>}
            {mode !== 'manual' && <label className={styles.checkbox}>
              <input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />启用自动调度
            </label>}
          </fieldset>
          </div>
          {error && <p className={`${styles.formError} shrink-0`} role="alert">{error}</p>}
          <DialogFooter className="shrink-0">
            <DialogClose render={<Button variant="outline" disabled={saving} />} disabled={saving}>取消</DialogClose>
            <Button type="submit" disabled={saving || !script}>{saving ? '保存中…' : '保存任务'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
