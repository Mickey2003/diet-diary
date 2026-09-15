/** AI 记忆 API 封装。 */
import client from './client';

export interface MemoryItem {
  id: number;
  content: string;
  category: string;
  source: string;
  importance: number;
  is_active: boolean;
  evidence?: string;
  created_at: string;
  last_used_at?: string;
}

export interface MemorySummary {
  count: number;
  by_category: Record<string, number>;
  prompt_preview: string;
  disclaimer: string;
}

export interface RebuildResult {
  new_memories: number;
  scanned_meals: number;
  disclaimer: string;
}

export const CATEGORY_LABELS: Record<string, string> = {
  preference: '偏好',
  habit: '习惯',
  health: '健康',
  goal: '目标',
  fact: '事实',
};

export const CATEGORY_COLORS: Record<string, string> = {
  preference: 'blue',
  habit: 'green',
  health: 'red',
  goal: 'gold',
  fact: 'purple',
};

export const VALID_CATEGORIES = Object.keys(CATEGORY_LABELS);

export const listMemories = (params?: {
  category?: string;
  include_inactive?: boolean;
}) =>
  client
    .get<MemoryItem[]>('/api/memory', { params })
    .then((r) => r.data);

export const createMemory = (data: {
  content: string;
  category: string;
  importance: number;
  evidence?: string;
}) => client.post<MemoryItem>('/api/memory', data).then((r) => r.data);

export const updateMemory = (
  id: number,
  data: {
    content?: string;
    category?: string;
    importance?: number;
    is_active?: boolean;
  },
) => client.patch<MemoryItem>(`/api/memory/${id}`, data).then((r) => r.data);

export const deleteMemory = (id: number) =>
  client.delete(`/api/memory/${id}`).then((r) => r.data);

export const extractMemories = (text: string) =>
  client
    .post<MemoryItem[]>('/api/memory/extract', { text })
    .then((r) => r.data);

export const rebuildMemories = () =>
  client.post<RebuildResult>('/api/memory/rebuild').then((r) => r.data);

export const getMemorySummary = () =>
  client.get<MemorySummary>('/api/memory/summary').then((r) => r.data);
