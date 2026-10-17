import React from 'react';
import { CheckCircle2, CircleDashed, XCircle } from 'lucide-react';
import { statusLabel, statusTone } from '@/utils/formatters.js';
import styles from './StatusBadge.module.css';

export default function StatusBadge({ status, label }) {
  const tone = statusTone(status);
  const Icon = tone === 'ok' ? CheckCircle2 : tone === 'bad' ? XCircle : CircleDashed;

  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      <Icon size={14} />
      {label || statusLabel(status)}
    </span>
  );
}
