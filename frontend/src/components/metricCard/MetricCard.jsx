import React from 'react';
import { formatValue } from '@/utils/formatters.js';
import styles from './MetricCard.module.css';

export default function MetricCard({ label, value, note, icon: Icon, tone = 'neutral' }) {
  return (
    <article className={styles.card}>
      <div className={styles.head}>
        <span>{label}</span>
        <div className={`${styles.icon} ${styles[tone] || styles.neutral}`}>
          <Icon size={17} />
        </div>
      </div>
      <strong>{formatValue(value)}</strong>
      <p>{note}</p>
    </article>
  );
}
