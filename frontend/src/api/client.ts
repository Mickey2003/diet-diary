import axios from 'axios';
import { message } from 'antd';

/** 未登录 / 会话过期时触发，App 监听后切换到登录页 */
export const UNAUTHORIZED_EVENT = 'dd:unauthorized';

const client = axios.create({
  baseURL: '/',
  timeout: 90000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // 会话保存在 HttpOnly Cookie 中
});

client.interceptors.response.use(
  (res) => res,
  (error) => {
    const status: number | undefined = error?.response?.status;
    const url: string = error?.config?.url ?? '';
    if (status === 401 && !url.startsWith('/api/auth/')) {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
      return Promise.reject(error);
    }
    const detail: unknown =
      error?.response?.data?.detail ??
      error?.message ??
      '请求失败，请检查网络或后端服务是否启动。';
    const detailStr = typeof detail === 'string' ? detail : JSON.stringify(detail);
    // 409 → warning toast (not error), caller handles polling
    if (status === 409) {
      message.warning(detailStr);
      return Promise.reject(error);
    }
    message.error(detailStr);
    return Promise.reject(error);
  }
);

export default client;
