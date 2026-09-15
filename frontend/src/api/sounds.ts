/** 就餐提醒音效 API 封装 */
import client from './client';

export interface SoundPreset {
  key: string;
  name: string;
  url: string;
  builtin?: boolean;
  hidden?: boolean;
  default_name?: string;
  id?: number;
}

export interface SoundFile {
  key: string;
  id: number;
  name: string;
  url: string;
  mime: string;
  size: number;
  created_at: string;
}

export interface AlertSettings {
  enabled: boolean;
  sound: string;
  lead_minutes: number;
  meal_types: string[];
  volume: number;
  vibrate: boolean;
  sound_url?: string;
}

export interface SoundsOut {
  presets: SoundPreset[];
  mine: SoundFile[];
  settings: AlertSettings;
  can_manage_presets?: boolean;
}

export interface AdminPresetsOut {
  presets: SoundPreset[];
  max_system: number;
}

export const getSounds = () =>
  client.get<SoundsOut>('/api/sounds').then((r) => r.data);

export const uploadSound = (file: File, name: string) => {
  const form = new FormData();
  form.append('file', file);
  form.append('name', name);
  return client
    .post<SoundFile>('/api/sounds', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

export const renameSound = (id: number, name: string) =>
  client.patch(`/api/sounds/${id}`, { name }).then((r) => r.data);

export const deleteSound = (id: number) =>
  client.delete(`/api/sounds/${id}`).then((r) => r.data);

export const getAlertSettings = () =>
  client.get<AlertSettings>('/api/sounds/alert-settings').then((r) => r.data);

export const putAlertSettings = (data: Partial<AlertSettings>) =>
  client.put<AlertSettings>('/api/sounds/alert-settings', data).then((r) => r.data);

export const testAlertSettings = () =>
  client.post('/api/sounds/alert-settings/test').then((r) => r.data);

// Admin-only endpoints
export const getAdminPresets = () =>
  client.get<AdminPresetsOut>('/api/sounds/admin/presets').then((r) => r.data);

export const uploadAdminPreset = (file: File, name: string) => {
  const form = new FormData();
  form.append('file', file);
  form.append('name', name);
  return client
    .post<{ presets: SoundPreset[] }>('/api/sounds/admin/presets', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((r) => r.data);
};

export const patchBuiltinPreset = (keyName: string, data: { name?: string; hidden?: boolean }) =>
  client
    .patch<{ presets: SoundPreset[] }>(`/api/sounds/admin/presets/builtin/${keyName}`, data)
    .then((r) => r.data);
