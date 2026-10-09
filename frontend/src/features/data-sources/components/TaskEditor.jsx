import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

import { Button } from '@/shadcn/components/ui/button.jsx';
import { Input } from '@/shadcn/components/ui/input.jsx';
import styles from './DataSourcesView.module.css';

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
  const dialog = useRef(null);

  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  function changeScript(value) {
    const selected = scripts.find(item => item.id === value);
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
    <dialog ref={dialog} className={styles.dialog} onCancel={event => { event.preventDefault(); if (!saving) onClose(); }} aria-labelledby="task-editor-title">
      <form onSubmit={submit} className={styles.form}>
        <div className={styles.editorHead}>
          <h3 id="task-editor-title">{task ? '编辑任务' : '新增任务'}</h3>
          <Button type="button" variant="ghost" size="icon" aria-label="关闭" onClick={onClose} disabled={saving}><X size={18} /></Button>
        </div>
        <fieldset disabled={saving} className={styles.fields}>
          <label htmlFor="task-name">任务名称</label>
          <Input id="task-name" required maxLength={100} value={name} onChange={event => setName(event.target.value)} autoFocus />
          <label htmlFor="task-script">执行脚本</label>
          <select id="task-script" value={scriptId} onChange={event => changeScript(event.target.value)} required>
            {scripts.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          {Object.hasOwn(script?.params || {}, 'lookback_days') && <>
            <label htmlFor="task-days">同步最近多少个自然日</label>
            <Input id="task-days" type="number" min="1" step="1" required value={days} onChange={event => setDays(event.target.value)} />
          </>}
          <label htmlFor="task-schedule">运行方式</label>
          <select id="task-schedule" value={mode} onChange={event => setMode(event.target.value)}>
            <option value="manual">仅手动运行</option>
            <option value="cron">按时间定时运行</option>
            <option value="interval">按固定间隔运行</option>
          </select>
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
        <div className={styles.editorActions}>
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>取消</Button>
          <Button type="submit" disabled={saving || !script}>{saving ? '保存中…' : '保存任务'}</Button>
        </div>
      </form>
    </dialog>
  );
}
