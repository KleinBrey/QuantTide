import { useRef, useState } from 'react';
import { X } from 'lucide-react';

import { Button } from '@/shadcn/components/ui/button.jsx';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shadcn/components/ui/dialog.jsx';
import { Input } from '@/shadcn/components/ui/input.jsx';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/shadcn/components/ui/select.jsx';
import styles from './DataSourcesView.module.css';

const RUN_MODES = [
  { value: 'manual', label: '仅手动运行' },
  { value: 'cron', label: '按时间定时运行' },
  { value: 'interval', label: '按固定间隔运行' }
];

export default function TaskEditor({ task, scripts, settings, onSave, onClose }) {
  const [scriptId, setScriptId] = useState(task?.script_id || scripts[0]?.id || '');
  const script = scripts.find(item => item.id === scriptId);
  const [name, setName] = useState(task?.name || script?.name || '');
  const [days, setDays] = useState(task?.params?.lookback_days ?? script?.params.lookback_days ?? 3);
  const [mode, setMode] = useState(task?.schedule?.trigger || 'manual');
  const [cron, setCron] = useState(task?.schedule?.cron || '0 16 * * mon-fri');
  const [seconds, setSeconds] = useState(task?.schedule?.seconds || 3600);
  const [enabled, setEnabled] = useState(task?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const nameInput = useRef(null);

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
        schedule = { trigger: 'cron', cron: cron.trim() };
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
      <DialogContent showCloseButton={false} initialFocus={nameInput}
        className="flex max-h-[90dvh] w-[520px] flex-col bg-card sm:max-w-[520px]">
        <form onSubmit={submit} className="flex min-h-0 flex-col gap-5">
          <DialogHeader className="shrink-0 flex-row items-center justify-between">
            <div>
              <DialogTitle className="text-xl font-bold">{task ? '编辑任务' : '新增任务'}</DialogTitle>
              <DialogDescription className="sr-only">设置同步任务的名称、执行脚本和运行时间。</DialogDescription>
            </div>
            <DialogClose render={<Button variant="ghost" size="icon" disabled={saving} />} aria-label="关闭" disabled={saving}>
              <X size={18} />
            </DialogClose>
          </DialogHeader>
          <fieldset disabled={saving} className={`${styles.fields} min-h-0 overflow-y-auto pr-1 [color-scheme:dark]`}>
            <label htmlFor="task-name">任务名称</label>
            <Input ref={nameInput} id="task-name" required maxLength={100} value={name} onChange={event => setName(event.target.value)} />
            <span id="task-script-label" className={styles.fieldLabel}>执行脚本</span>
            {/* 弹窗管理背景隔离，下拉无需再次锁定页面滚动。 */}
            <Select value={scriptId} onValueChange={changeScript} disabled={saving} required modal={false}
              items={scripts.map(item => ({ value: item.id, label: item.name }))}>
              <SelectTrigger id="task-script" aria-labelledby="task-script-label"><SelectValue placeholder="选择执行脚本" /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {scripts.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            {Object.hasOwn(script?.params || {}, 'lookback_days') && <>
              <label htmlFor="task-days">同步最近多少个自然日</label>
              <Input id="task-days" type="number" min="1" step="1" required value={days} onChange={event => setDays(event.target.value)} />
            </>}
            <span id="task-schedule-label" className={styles.fieldLabel}>运行方式</span>
            <Select value={mode} onValueChange={setMode} items={RUN_MODES} disabled={saving} modal={false}>
              <SelectTrigger id="task-schedule" aria-labelledby="task-schedule-label"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {RUN_MODES.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            {mode === 'cron' && <>
              <label htmlFor="task-cron">定时规则</label>
              <Input id="task-cron" required value={cron} onChange={event => setCron(event.target.value)} placeholder="0 16 * * mon-fri" aria-describedby="cron-help" />
              <p id="cron-help" className={styles.help}>依次填写：分 时 日 月 星期。例如 0 16 * * mon-fri 表示工作日 16:00；星期使用 mon 至 sun。时区：{settings.timezone}。</p>
            </>}
            {mode === 'interval' && <>
              <label htmlFor="task-seconds">执行间隔（秒）</label>
              <Input id="task-seconds" type="number" min="1" step="1" required value={seconds} onChange={event => setSeconds(event.target.value)} />
            </>}
            {mode !== 'manual' && <label className={styles.checkbox}>
              <input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />启用自动调度
            </label>}
          </fieldset>
          {error && <p className={styles.formError} role="alert">{error}</p>}
          <DialogFooter className="shrink-0">
            <DialogClose render={<Button variant="outline" disabled={saving} />} disabled={saving}>取消</DialogClose>
            <Button type="submit" disabled={saving || !script}>{saving ? '保存中…' : '保存任务'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
