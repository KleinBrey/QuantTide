import { useState } from 'react';
import { CalendarDays, Check, ChevronDown, Loader2, Play } from 'lucide-react';
import { Popover, Select } from 'radix-ui';
import { format, parseISO } from 'date-fns';
import { zhCN } from 'react-day-picker/locale';
import { Calendar } from '@/shadcn/components/ui/calendar.jsx';
import { Button } from '@/shadcn/components/ui/button.jsx';
import styles from './BacktestResultsView.module.css';

export default function BacktestToolbar({ strategies, params, setParams, loading, runBacktest }) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const selectedStrategy = strategies.find(strategy => strategy.id === params.strategy);
  const dateRange = {
    from: params.start_date ? parseISO(params.start_date) : undefined,
    to: params.end_date ? parseISO(params.end_date) : undefined
  };

  function selectRange(range) {
    setParams(current => ({
      ...current,
      start_date: range.from ? format(range.from, 'yyyy-MM-dd') : '',
      end_date: range.to ? format(range.to, 'yyyy-MM-dd') : ''
    }));
    if (range.to) setCalendarOpen(false);
  }

  function updateField(event) {
    const { name, value } = event.target;
    setParams(current => ({ ...current, [name]: value }));
  }

  function submit(event) {
    event.preventDefault();
    if (params.start_date && params.end_date) runBacktest(params);
  }

  return (
    <form className={`dashboard-panel ${styles.toolbar}`} onSubmit={submit}>
      <fieldset className={styles.toolbarFields} disabled={loading}>
        <label className={styles.strategyField}>
          <span>回测策略</span>
          <Select.Root
            value={params.strategy}
            onValueChange={strategy => {
              // 异步选项挂载时，忽略原生 select 同步产生的空值。
              if (strategy) setParams(current => ({ ...current, strategy }));
            }}
            disabled={loading}
          >
            <Select.Trigger className={styles.strategySelect} aria-label="回测策略">
              <Select.Value placeholder="选择回测策略">{selectedStrategy?.name}</Select.Value>
              <Select.Icon>
                <ChevronDown size={15} />
              </Select.Icon>
            </Select.Trigger>
            <Select.Portal>
              <Select.Content className={styles.strategyMenu} position="popper" sideOffset={6} align="start">
                <Select.Viewport>
                  {strategies.map(strategy => (
                    <Select.Item className={styles.strategyOption} key={strategy.id} value={strategy.id}>
                      <Select.ItemText>{strategy.name}</Select.ItemText>
                      <Select.ItemIndicator>
                        <Check size={15} />
                      </Select.ItemIndicator>
                    </Select.Item>
                  ))}
                </Select.Viewport>
              </Select.Content>
            </Select.Portal>
          </Select.Root>
        </label>
        <div className={styles.dateRangeField}>
          <span id="backtest-date-label">回测日期</span>
          <Popover.Root open={calendarOpen} onOpenChange={setCalendarOpen}>
            <Popover.Trigger asChild>
              <Button
                type="button"
                variant="outline"
                className={styles.dateRangeButton}
                aria-labelledby="backtest-date-label backtest-date-value"
                disabled={loading}
              >
                <CalendarDays size={15} />
                <span id="backtest-date-value">
                  {params.start_date ? `${params.start_date} ~ ${params.end_date || '选择结束日期'}` : '选择日期范围'}
                </span>
              </Button>
            </Popover.Trigger>
            <Popover.Portal>
              <Popover.Content
                className={styles.dateRangePopover}
                align="start"
                sideOffset={8}
                collisionPadding={12}
                aria-label="选择回测日期范围"
              >
                <Calendar
                  mode="range"
                  required
                  locale={zhCN}
                  selected={dateRange}
                  onSelect={selectRange}
                  defaultMonth={dateRange.from}
                  captionLayout="dropdown"
                  numberOfMonths={2}
                  showOutsideDays={false}
                />
              </Popover.Content>
            </Popover.Portal>
          </Popover.Root>
        </div>
        <label>
          <span>最大持仓数</span>
          <input
            type="number"
            name="max_positions"
            value={params.max_positions}
            min="1"
            max="100"
            step="1"
            onChange={updateField}
            required
          />
        </label>
        <label>
          <span>每股最大占比（%）</span>
          <input
            type="number"
            name="max_position_pct"
            value={params.max_position_pct}
            min="0.01"
            max="100"
            step="0.01"
            onChange={updateField}
            required
          />
        </label>
        <Button
          type="submit"
          className="dashboard-ghost-button"
          variant="outline"
          disabled={loading || !params.strategy || !params.start_date || !params.end_date}
        >
          {loading ? <Loader2 className="dashboard-spin" size={15} /> : <Play size={15} />}
          {loading ? '回测中…' : '执行回测'}
        </Button>
      </fieldset>
    </form>
  );
}
