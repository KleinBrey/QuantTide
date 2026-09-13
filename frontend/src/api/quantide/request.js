import { HttpClient } from '../request.js';

export class QuantClient extends HttpClient {
  handleRequest(config) {
    return config;
  }

  handleResponse(response) {
    return response;
  }

  handleResponseError(error) {
    const serverMessage = error.response?.data?.detail || error.response?.data?.error;

    // FastAPI 的具体错误信息位于 response.data.detail。
    // 写回 message 后，业务层可以继续统一读取 error.message。
    if (typeof serverMessage === 'string' && serverMessage) {
      error.message = serverMessage;
    }

    return super.handleResponseError(error);
  }
}

// 创建Quant连接
const request = new QuantClient({
  baseURL: import.meta.env.VITE_QUANT_API_URL || 'http://127.0.0.1:8001'
});

export default request;
