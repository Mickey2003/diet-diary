import client from './client';

export interface UsageStats {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  failed: number;
  est_cost: number;
}

export interface DailyUsage {
  date: string;
  calls: number;
  tokens: number;
}

export interface TaskUsage {
  task: string;
  calls: number;
  tokens: number;
}

export interface UserUsage {
  username: string;
  calls: number;
  tokens: number;
}

export interface RecentCall {
  id: number;
  task: string;
  model: string;
  provider: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  ok: boolean;
  error: string | null;
  created_at: string;
}

export interface UsageSummary {
  scope: 'all' | 'self';
  price: { input_per_1k: number; output_per_1k: number; currency: string };
  today: UsageStats;
  month: UsageStats;
  total: UsageStats;
  mine_month: UsageStats;
  daily: DailyUsage[];
  by_task: TaskUsage[];
  by_user?: UserUsage[];
  recent: RecentCall[];
}

export interface BalanceEntry {
  currency: string;
  total: number;
  granted: number;
  topped_up: number;
}

export interface BalanceInfo {
  provider: string;
  supported: boolean;
  console_url: string;
  ok?: boolean;
  balances?: BalanceEntry[];
  message?: string;
  is_available?: boolean;
  checked_at: string;
}

export const TASK_LABELS: Record<string, string> = {
  vision: '图片识别',
  plan: '查询规划',
  explain: '结果解释',
  report: '阶段总结',
  meal_plan: '餐单',
  meal_plan_slot: '餐单换一换',
  memory_extract: '记忆抽取',
  share_copy: '分享文案',
  generic: '其他',
};

export const getUsageSummary = () =>
  client.get<UsageSummary>('/api/usage/summary').then((r) => r.data);

export const getUsageBalance = () =>
  client.get<BalanceInfo>('/api/usage/balance').then((r) => r.data);

export const updateUsagePrice = (data: {
  input_per_1k?: number;
  output_per_1k?: number;
  currency?: string;
}) => client.put<{ ok: boolean }>('/api/usage/price', data).then((r) => r.data);
