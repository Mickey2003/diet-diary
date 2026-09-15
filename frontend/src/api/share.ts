import client from './client';

export interface ShareCardIn {
  kind: 'weekly' | 'monthly' | 'today' | 'meal';
  anchor?: string;
  meal_id?: number;
  tone?: string;
}

export interface ShareCardOut {
  card: {
    title: string;
    subtitle?: string;
    stats?: { label: string; value: string | number }[];
    highlight?: string;
    theme: string;
    date_range?: string;
  };
  copy: {
    headline: string;
    body: string;
    hashtags: string[];
    emoji?: string;
  };
  disclaimer?: string;
  created_at?: string;
}

export interface ShareHistoryItem {
  created_at: string;
  kind: string;
  tone: string;
  image_url?: string | null;
  copy?: {
    headline: string;
    body: string;
    hashtags: string[];
  };
  card?: ShareCardOut['card'];
}

export const generateShareCard = (payload: ShareCardIn) =>
  client.post<ShareCardOut>('/api/share/card', payload).then((r) => r.data);

export const getShareHistory = (limit = 20) =>
  client.get<ShareHistoryItem[]>('/api/share/history', { params: { limit } }).then((r) => r.data);

/** 把前端渲染好的卡片图片上传到服务端，便于历史记录中查看/下载 */
export const attachShareImage = (dataUrl: string, createdAt?: string) =>
  client
    .post<{ image_url: string }>('/api/share/history/image', {
      data_url: dataUrl,
      created_at: createdAt,
    })
    .then((r) => r.data);
