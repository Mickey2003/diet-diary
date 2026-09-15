import client from './client';

// ---------- Types ----------

export interface ChannelField {
  name: string;
  label: string;
  type: 'text' | 'number' | 'password' | 'boolean' | 'select';
  secret?: boolean;
  placeholder?: string;
  options?: { label: string; value: string }[];
}

export interface ChannelMeta {
  key: string;
  label: string;
  help: string;
  fields: ChannelField[];
}

export interface DailyReminderSchedule {
  enabled: boolean;
  time: string;
  only_if_no_meals: boolean;
}

export interface DailySummarySchedule {
  enabled: boolean;
  time: string;
}

export interface WeeklyReportSchedule {
  enabled: boolean;
  weekday: number;
  time: string;
}

export interface NotifySchedules {
  daily_reminder: DailyReminderSchedule;
  daily_summary: DailySummarySchedule;
  weekly_report: WeeklyReportSchedule;
}

export interface NotifyConfig {
  channels: Record<string, Record<string, unknown>>;
  schedules: NotifySchedules;
}

export interface NotifySettingsOut {
  config: NotifyConfig;
  channel_meta: ChannelMeta[];
  kinds: { key: string; label: string }[];
  mask: string;
  enabled_channels: string[];
}

export interface NotifyTestOut {
  channel: string;
  ok: boolean;
  detail: string;
}

export interface NotifySendResult {
  channel: string;
  ok: boolean;
  detail: string;
}

export interface NotifySendOut {
  sent: boolean;
  reason?: string;
  results: NotifySendResult[];
}

export interface NotifyPreviewOut {
  kind: string;
  skipped: boolean;
  reason?: string;
  title?: string;
  text?: string;
  markdown?: string;
  sms_params?: string[];
}

export interface NotifyLogItem {
  id: number;
  kind: string;
  kind_label: string;
  channel: string;
  ok: boolean;
  detail: string;
  created_at: string;
}

// ---------- API wrappers ----------

export const getNotifySettings = () =>
  client.get<NotifySettingsOut>('/api/notify/settings').then((r) => r.data);

export const putNotifySettings = (config: NotifyConfig) =>
  client.put<NotifySettingsOut>('/api/notify/settings', { config }).then((r) => r.data);

export const testNotifyChannel = (channel: string, kind?: string) =>
  client
    .post<NotifyTestOut>('/api/notify/test', { channel, kind: kind ?? 'test' })
    .then((r) => r.data);

export const sendNotifyNow = (kind: string) =>
  client.post<NotifySendOut>('/api/notify/send', { kind }).then((r) => r.data);

export const previewNotify = (kind: string) =>
  client
    .get<NotifyPreviewOut>('/api/notify/preview', { params: { kind } })
    .then((r) => r.data);

export const getNotifyLogs = (limit = 50) =>
  client
    .get<NotifyLogItem[]>('/api/notify/logs', { params: { limit } })
    .then((r) => r.data);
