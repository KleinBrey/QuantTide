import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, GripVertical, LockKeyhole, Pencil, Settings2, Trash2, X } from 'lucide-react';
import { Popover } from 'radix-ui';
import styles from './MarketStockBrowser.module.css';

function reordered(groups, sourceId, targetId) {
  const next = [...groups];
  const from = next.findIndex(group => group.id === sourceId);
  const to = next.findIndex(group => group.id === targetId);
  if (from < 0 || to < 0 || from === to) return null;
  next.splice(to, 0, next.splice(from, 1)[0]);
  return next;
}

export default function MarketStockGroups({ marketId, groups, groupId, selectGroup, createGroup, renameGroup,
  deleteGroup, reorderGroups, loading, mutating, actionError }) {
  const [open, setOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [editId, setEditId] = useState(null);
  const [editName, setEditName] = useState('');
  const [deleteId, setDeleteId] = useState(null);
  const dragRef = useRef(null);
  const tabsRef = useRef(null);
  const editorRef = useRef(null);
  const disabled = loading || mutating;

  useEffect(() => {
    setOpen(false);
    setNewName('');
    setEditId(null);
    setEditName('');
    setDeleteId(null);
    dragRef.current = null;
  }, [marketId]);

  useEffect(() => {
    tabsRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [groupId, groups]);

  useEffect(() => {
    editorRef.current?.scrollIntoView({ block: 'nearest' });
  }, [editId, deleteId]);

  const drop = (event, targetId) => {
    event.preventDefault();
    if (disabled) return;
    const next = reordered(groups, dragRef.current, targetId);
    dragRef.current = null;
    if (next) reorderGroups(next);
  };
  const move = (index, direction) => {
    const target = groups[index + direction];
    if (target) reorderGroups(reordered(groups, groups[index].id, target.id));
  };

  return (
    <div aria-busy={loading} className={styles.groupBar}>
      <div ref={tabsRef} aria-label="自选分组" className={styles.groupTabs} role="tablist">
        {groups.map(group => (
          <button key={group.id} className={styles.groupTab} aria-selected={group.id === groupId} role="tab"
            disabled={disabled} draggable={!disabled} type="button" title={`${group.name}${group.is_default ? ' · 默认分组，不可删除' : ''}`}
            onClick={() => selectGroup(group.id)}
            onDragStart={event => { dragRef.current = group.id; event.dataTransfer.setData('text/plain', String(group.id)); }}
            onDragEnd={() => { dragRef.current = null; }} onDragOver={event => event.preventDefault()} onDrop={event => drop(event, group.id)}>
            {group.name}
          </button>
        ))}
        {!groups.length && <span className={styles.groupLoading}>{loading ? '加载分组…' : '自选分组'}</span>}
      </div>
      <Popover.Root open={open} onOpenChange={next => { if (!mutating) { setOpen(next); setEditId(null); setDeleteId(null); } }}>
        <Popover.Trigger asChild>
          <button aria-label="管理自选分组" className={styles.groupManageButton} disabled={disabled} type="button" title="管理自选分组"><Settings2 size={19} strokeWidth={2.2} /></button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content align="start" aria-label="管理自选分组" className={`${styles.addPopover} ${styles.groupPopover}`} collisionPadding={8} sideOffset={8}>
            <div className={styles.addTitle}><span>自选分组</span><Popover.Close aria-label="关闭分组管理" className={styles.closeButton} disabled={mutating}><X size={16} /></Popover.Close></div>
            <p className={styles.groupHint}>拖拽标签或使用箭头调整顺序</p>
            <div className={styles.manageGroups}>
              {groups.map((group, index) => (
                <div key={group.id}>
                  <div className={styles.manageGroupRow} data-active={group.id === groupId || undefined} draggable={!disabled}
                    onDragStart={event => { dragRef.current = group.id; event.dataTransfer.setData('text/plain', String(group.id)); }}
                    onDragEnd={() => { dragRef.current = null; }} onDragOver={event => event.preventDefault()} onDrop={event => drop(event, group.id)}>
                    <GripVertical size={13} />
                    <button className={styles.manageGroupName} aria-pressed={group.id === groupId} disabled={disabled} onClick={() => { selectGroup(group.id); setOpen(false); }} type="button">{group.name}</button>
                    <span className={styles.groupLock}>{Boolean(group.is_default) && <LockKeyhole size={12} aria-label="默认分组不可删除" />}</span>
                    <div className={styles.manageGroupActions}>
                      <button className={styles.closeButton} aria-label={`上移分组 ${group.name}`} disabled={disabled || index === 0} onClick={() => move(index, -1)} type="button"><ArrowUp size={13} /></button>
                      <button className={styles.closeButton} aria-label={`下移分组 ${group.name}`} disabled={disabled || index === groups.length - 1} onClick={() => move(index, 1)} type="button"><ArrowDown size={13} /></button>
                      {!group.is_default && <>
                        <button className={styles.closeButton} aria-label={`重命名分组 ${group.name}`} disabled={disabled} onClick={() => { setEditId(group.id); setEditName(group.name); setDeleteId(null); }} type="button"><Pencil size={13} /></button>
                        <button className={styles.closeButton} aria-label={`删除分组 ${group.name}`} disabled={disabled} onClick={() => { setDeleteId(group.id); setEditId(null); }} type="button"><Trash2 size={13} /></button>
                      </>}
                    </div>
                  </div>
                  {editId === group.id && <form ref={editorRef} className={styles.groupEditForm} onSubmit={async event => { event.preventDefault(); if (await renameGroup(group.id, editName.trim())) setEditId(null); }}>
                    <input aria-label="新分组名称" disabled={disabled} required maxLength={100} value={editName} onChange={event => setEditName(event.target.value)} />
                    <div className={styles.listActions}>
                      <button className={styles.addButton} disabled={disabled || !editName.trim()} type="submit">保存</button>
                      <button className={styles.addButton} disabled={disabled} onClick={() => setEditId(null)} type="button">取消</button>
                    </div>
                  </form>}
                  {deleteId === group.id && <div ref={editorRef} className={styles.deleteGroupPrompt}>
                    <p>删除“{group.name}”及其中的自选条目？</p>
                    <div className={styles.listActions}>
                      <button className={styles.addButton} disabled={disabled} onClick={async () => { if (await deleteGroup(group.id)) setDeleteId(null); }} type="button">确认删除</button>
                      <button className={styles.addButton} disabled={disabled} onClick={() => setDeleteId(null)} type="button">取消</button>
                    </div>
                  </div>}
                </div>
              ))}
            </div>
            <form className={styles.createGroupForm} onSubmit={async event => {
              event.preventDefault();
              if (await createGroup(newName.trim())) { setNewName(''); setOpen(false); }
            }}>
              <label>新建分组<input aria-label="分组名称" autoComplete="off" disabled={disabled} required maxLength={100} value={newName} onChange={event => setNewName(event.target.value)} placeholder="例如 AI算力" /></label>
              <button className={styles.submitButton} disabled={disabled || !newName.trim()} type="submit">＋ 新建分组</button>
            </form>
            {actionError && <p className={styles.formError} role="alert">{actionError}</p>}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
