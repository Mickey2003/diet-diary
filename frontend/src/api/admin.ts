import client from './client';

export interface AdminUserOut {
  id: number;
  username: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  is_approved: boolean;
  totp_enabled: boolean;
  created_at: string;
  meal_count: number;
}

export interface AdminUserCreate {
  username: string;
  password: string;
  role: string;
  display_name?: string;
}

export interface AdminUserPatch {
  role?: string;
  is_active?: boolean;
  display_name?: string;
  new_password?: string;
  reset_totp?: boolean;
}

export const listAdminUsers = () =>
  client.get<AdminUserOut[]>('/api/admin/users').then((r) => r.data);

export const createAdminUser = (payload: AdminUserCreate) =>
  client.post<AdminUserOut>('/api/admin/users', payload).then((r) => r.data);

export const patchAdminUser = (userId: number, payload: AdminUserPatch) =>
  client.patch<AdminUserOut>(`/api/admin/users/${userId}`, payload).then((r) => r.data);

export const deleteAdminUser = (userId: number) =>
  client.delete(`/api/admin/users/${userId}`).then((r) => r.data);

export const approveAdminUser = (userId: number) =>
  client.post<AdminUserOut>(`/api/admin/users/${userId}/approve`).then((r) => r.data);
