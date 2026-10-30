import request from '@/api/quantide/request.js';

export const getCryptoSymbols = () => request.get('/api/crypto/symbols');
export const getCryptoBars = symbol => request.get(`/api/crypto/daily-bars/${encodeURIComponent(symbol)}`);
export const syncCryptoBars = symbol => request.post('/api/crypto/sync', { symbol }, { timeout: 60000 });
