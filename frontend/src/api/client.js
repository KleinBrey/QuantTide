const API_BASE_URLS = [import.meta.env.VITE_API_BASE_URL, 'http://127.0.0.1:18765'].filter(Boolean);

function networkError(lastError) {
  const targets = API_BASE_URLS.join('、');
  const error = new Error(`无法连接后端（${targets}），请确认后端服务已启动`);
  error.cause = lastError;
  error.isNetworkError = true;
  return error;
}

export async function apiGet(path, options = {}) {
  let lastError = null;

  for (const baseUrl of API_BASE_URLS) {
    try {
      const response = await fetch(`${baseUrl}${path}`, options);
      const payload = await response.json();
      if (!response.ok) {
        const error = new Error(payload.error || payload.detail || '请求失败');
        error.responseReceived = true;
        throw error;
      }
      return payload;
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      if (err.responseReceived) throw err;
      lastError = err;
    }
  }

  throw networkError(lastError);
}

export async function apiPost(path, body, options = {}) {
  let lastError = null;

  for (const baseUrl of API_BASE_URLS) {
    try {
      const response = await fetch(`${baseUrl}${path}`, {
        ...options,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        body: JSON.stringify(body)
      });
      const payload = await response.json();
      if (!response.ok) {
        const error = new Error(payload.error || payload.detail || '请求失败');
        error.responseReceived = true;
        throw error;
      }
      return payload;
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      if (err.responseReceived) throw err;
      lastError = err;
    }
  }

  throw networkError(lastError);
}
