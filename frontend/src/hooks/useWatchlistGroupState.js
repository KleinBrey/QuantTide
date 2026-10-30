import { useCallback, useState } from 'react';

// 路由卸载后保留分组和各市场的选中项，重新进入时直接显示，再由页面刷新数据。
let savedGroups = [];
let savedActiveGroups = {};

export function useWatchlistGroupState() {
  const [allGroups, updateGroups] = useState(() => savedGroups);
  const [activeGroups, updateActiveGroups] = useState(() => savedActiveGroups);

  const setAllGroups = useCallback(groups => {
    savedGroups = groups;
    updateGroups(groups);
  }, []);

  const setActiveGroups = useCallback(update => {
    savedActiveGroups = update(savedActiveGroups);
    updateActiveGroups(savedActiveGroups);
  }, []);

  return { allGroups, setAllGroups, activeGroups, setActiveGroups };
}
