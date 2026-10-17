import React from 'react';
import { Blocks } from 'lucide-react';
import styles from './PlaceholderDashboard.module.css';

export default function PlaceholderDashboard({ title, description }) {
  return (
    <section className={styles.placeholder}>
      <Blocks size={34} />
      <h2>{title || '看板'}</h2>
      <p>{description || '这个看板还没有接入数据。'}</p>
    </section>
  );
}
