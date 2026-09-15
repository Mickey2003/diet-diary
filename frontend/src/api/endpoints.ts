import client from './client';
import type {
  MetaOut,
  TagOut,
  RecognizeOut,
  MealOut,
  MealPage,
  MealCreate,
  MealUpdate,
  StatsOut,
  QueryOut,
  QueryHistoryItem,
  ReportOut,
  SettingsOut,
  ConnectionTestOut,
} from './types';

// ---------- meta ----------
export const getMeta = () =>
  client.get<MetaOut>('/api/meta').then((r) => r.data);

export const getTags = () =>
  client.get<TagOut[]>('/api/tags').then((r) => r.data);

// ---------- 识别 ----------
export const recognizeMeal = (file: File) => {
  const fd = new FormData();
  fd.append('file', file);
  return client
    .post<RecognizeOut>('/api/meals/recognize', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

export const recognizeByPath = (image_path: string) =>
  client
    .post<RecognizeOut>('/api/meals/recognize-path', { image_path })
    .then((r) => r.data);

export const uploadOnly = (file: File) => {
  const fd = new FormData();
  fd.append('file', file);
  return client
    .post<{ image_path: string; image_url: string }>('/api/meals/upload-only', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

// ---------- 餐食记录 CRUD ----------
export const createMeal = (data: MealCreate) =>
  client.post<MealOut>('/api/meals', data).then((r) => r.data);

export const listMeals = (params: Record<string, string | number | undefined>) =>
  client.get<MealPage>('/api/meals', { params }).then((r) => r.data);

export const getMeal = (id: number) =>
  client.get<MealOut>(`/api/meals/${id}`).then((r) => r.data);

export const updateMeal = (id: number, data: MealUpdate) =>
  client.put<MealOut>(`/api/meals/${id}`, data).then((r) => r.data);

export const deleteMeal = (id: number) =>
  client.delete(`/api/meals/${id}`).then((r) => r.data);

// ---------- 统计 ----------
export const getStats = (range: 'week' | 'month', anchor?: string) =>
  client
    .get<StatsOut>('/api/stats', { params: { range, anchor } })
    .then((r) => r.data);

// ---------- 查询 ----------
export const runQuery = (question: string) =>
  client.post<QueryOut>('/api/query', { question }).then((r) => r.data);

export const getQueryHistory = (limit = 20) =>
  client
    .get<QueryHistoryItem[]>('/api/query/history', { params: { limit } })
    .then((r) => r.data);

// ---------- 报告 ----------
export const createReport = (period_type: 'week' | 'month', anchor?: string) =>
  client
    .post<ReportOut>('/api/reports', { period_type, anchor })
    .then((r) => r.data);

export const listReports = () =>
  client.get<ReportOut[]>('/api/reports').then((r) => r.data);

export const getReportGenerating = () =>
  client.get<{ generating: boolean }>('/api/reports/generating').then((r) => r.data);

export const getReport = (id: number) =>
  client.get<ReportOut>(`/api/reports/${id}`).then((r) => r.data);

export const deleteReport = (id: number) =>
  client.delete(`/api/reports/${id}`).then((r) => r.data);

// ---------- 设置 ----------
export const getSettings = () =>
  client.get<SettingsOut>('/api/settings').then((r) => r.data);

export const updateSettings = (data: {
  provider?: string;
  base_url?: string;
  text_model?: string;
  fast_model?: string;
  vision_model?: string;
  image_model?: string;
  vision_async?: boolean;
  net_proxy_mode?: string;
  barcode_sources?: string;
  dish_ai_images?: boolean;
  api_key?: string;
  // 生图专用 API（v0.8.6）
  image_provider?: string;
  image_base_url?: string;
  /** 生图专用模型 id（独立于旧的 image_model） */
  image_model_id?: string;
  image_api_key?: string;
  image_size?: string;
  image_emoji_fallback?: boolean;
}) => client.put<SettingsOut>('/api/settings', data).then((r) => r.data);

export interface PendingTasks {
  plan: boolean;
  slot: boolean;
  report: boolean;
  query: boolean;
  share: boolean;
  vision: boolean;
  memory: boolean;
}

export const getPendingTasks = () =>
  client.get<PendingTasks>('/api/tasks/pending').then((r) => r.data);

export const testConnection = () =>
  client.post<ConnectionTestOut>('/api/settings/test').then((r) => r.data);

/** 真发一张小图，验证「生图专用 API」是否可用（较慢，约 5~30 秒）。 */
export const testImageConnection = () =>
  client
    .post<ConnectionTestOut>('/api/settings/image/test', {}, { timeout: 180000 })
    .then((r) => r.data);

export interface NetProxyStatus {
  mode: string;
  enabled: boolean;
  detected: boolean | null;
  url: string;
}

export const getNetProxyStatus = (force = false) =>
  client
    .get<NetProxyStatus>('/api/settings/net-proxy/status', { params: { force } })
    .then((r) => r.data);
