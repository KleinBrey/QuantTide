import request from '@/api/quantide/request.js';

export const fetchTasks = () => request.get('/api/tasks');
export const reorderTasks = ids => request.put('/api/tasks/order', { ids });
export const fetchScripts = () => request.get('/api/tasks/scripts');
export const createTask = data => request.post('/api/tasks', data);
export const updateTask = (id, data) => request.put(`/api/tasks/${id}`, data);
export const deleteTask = id => request.delete(`/api/tasks/${id}`);
export const setTaskEnabled = (id, enabled) => request.patch(`/api/tasks/${id}`, { enabled });
export const runTask = id => request.post(`/api/tasks/${id}/run`, {}, { timeout: 0 });
export const fetchLatestUpdateTimes = () => request.get('/api/database-sync/latest-update-times');
