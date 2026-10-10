export const SCHEDULE_PERIODS = [
  { value: 'workdays', label: '工作日' },
  { value: 'daily', label: '每天' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' }
];

export const WEEKDAYS = [
  { value: 'mon', label: '周一' },
  { value: 'tue', label: '周二' },
  { value: 'wed', label: '周三' },
  { value: 'thu', label: '周四' },
  { value: 'fri', label: '周五' },
  { value: 'sat', label: '周六' },
  { value: 'sun', label: '周日' }
];

function parseWeekdays(value) {
  const selected = new Set();
  const indexOf = day => (/^\d$/.test(day) ? Number(day) : WEEKDAYS.findIndex(item => item.value === day));
  for (const part of value.split(',')) {
    const range = part.split('-');
    if (range.length > 2) return null;
    const start = indexOf(range[0]);
    const end = range.length === 2 ? indexOf(range[1]) : start;
    // APScheduler 的数字星期从周一（0）到周日（6）。
    if (start < 0 || end > 6 || end < start) return null;
    for (let index = start; index <= end; index += 1) selected.add(WEEKDAYS[index].value);
  }
  return WEEKDAYS.filter(day => selected.has(day.value)).map(day => day.value);
}

export function parseTaskCron(cron) {
  const defaults = { period: 'workdays', time: '16:00', weekdays: ['mon'], monthDay: '1' };
  if (!cron) return defaults;
  const fields = cron.trim().toLowerCase().split(/\s+/);
  const [minute, hour, day, month, weekday] = fields;
  const custom = { ...defaults, period: 'custom' };
  if (
    fields.length !== 5 ||
    !/^\d{1,2}$/.test(minute) ||
    !/^\d{1,2}$/.test(hour) ||
    Number(minute) > 59 ||
    Number(hour) > 23 ||
    month !== '*'
  )
    return custom;
  const time = `${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`;
  if (day === '*' && weekday === '*') return { ...defaults, period: 'daily', time };
  if (weekday === '*' && /^\d{1,2}$/.test(day) && Number(day) >= 1 && Number(day) <= 31) {
    return { ...defaults, period: 'monthly', time, monthDay: String(Number(day)) };
  }
  if (day !== '*') return custom;
  const weekdays = parseWeekdays(weekday);
  if (!weekdays?.length) return custom;
  const period = weekdays.join(',') === 'mon,tue,wed,thu,fri' ? 'workdays' : weekdays.length === 7 ? 'daily' : 'weekly';
  return { ...defaults, period, time, weekdays: period === 'weekly' ? weekdays : defaults.weekdays };
}

export function buildTaskCron({ period, time, weekdays, monthDay }) {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(time)) throw new Error('请选择有效的执行时间');
  const [hour, minute] = time.split(':').map(Number);
  const prefix = `${minute} ${hour}`;
  if (period === 'workdays') return `${prefix} * * mon-fri`;
  if (period === 'daily') return `${prefix} * * *`;
  if (period === 'monthly' && /^\d{1,2}$/.test(monthDay) && Number(monthDay) >= 1 && Number(monthDay) <= 31) {
    return `${prefix} ${Number(monthDay)} * *`;
  }
  if (period === 'weekly') {
    const selected = WEEKDAYS.filter(day => weekdays.includes(day.value));
    if (!selected.length) throw new Error('请至少选择一个执行星期');
    return `${prefix} * * ${selected.map(day => day.value).join(',')}`;
  }
  throw new Error('请选择有效的执行周期和日期');
}

export function formatTaskCron(cron) {
  const schedule = parseTaskCron(cron);
  const { period, time, weekdays, monthDay } = schedule;
  if (period === 'custom') return cron;
  if (period === 'weekly')
    return `每周${WEEKDAYS.filter(day => weekdays.includes(day.value))
      .map(day => day.label.slice(1))
      .join('、')} ${time}`;
  if (period === 'monthly') return `每月 ${monthDay} 日 ${time}`;
  return `${SCHEDULE_PERIODS.find(item => item.value === period).label} ${time}`;
}
