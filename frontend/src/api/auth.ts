import client from './client';

export interface AuthStatus {
  authenticated: boolean;
  username: string | null;
  role: string | null;
  is_admin: boolean;
  display_name: string | null;
  users_exist: boolean;
  allow_registration?: boolean;
  require_approval?: boolean;
}

export interface RegisterResult {
  ok: boolean;
  username: string;
  display_name: string | null;
  role: string;
  pending_approval?: boolean;
  message?: string;
  expires_at?: string;
}
export interface LoginResult {
  need_totp: boolean;
  pending_token?: string;
  username?: string;
  expires_at?: string;
}
export interface MeOut {
  id: number;
  username: string;
  display_name?: string | null;
  role: string;
  is_admin: boolean;
  totp_enabled: boolean;
  backup_codes_left: number;
  sessions: number;
}
export interface TotpSetupOut {
  secret: string;
  otpauth_uri: string;
  qr_data_url: string;
}

export const getAuthStatus = () => client.get<AuthStatus>('/api/auth/status').then((r) => r.data);

export const register = (
  username: string,
  password: string,
  display_name?: string,
) =>
  client
    .post<RegisterResult>('/api/auth/register', { username, password, display_name })
    .then((r) => r.data);

export const login = (username: string, password: string, remember: boolean) =>
  client.post<LoginResult>('/api/auth/login', { username, password, remember }).then((r) => r.data);

export const loginTotp = (pending_token: string, code: string) =>
  client.post<LoginResult>('/api/auth/login/totp', { pending_token, code }).then((r) => r.data);

export const logout = () => client.post('/api/auth/logout').then((r) => r.data);
export const logoutAll = () => client.post<{ revoked: number }>('/api/auth/logout-all').then((r) => r.data);

export const getMe = () => client.get<MeOut>('/api/auth/me').then((r) => r.data);

export const changePassword = (current_password: string, new_password: string) =>
  client.post('/api/auth/password', { current_password, new_password }).then((r) => r.data);

export const totpSetup = (password: string) =>
  client.post<TotpSetupOut>('/api/auth/totp/setup', { password }).then((r) => r.data);

export const totpEnable = (code: string) =>
  client.post<{ ok: boolean; backup_codes: string[] }>('/api/auth/totp/enable', { code }).then((r) => r.data);

export const totpDisable = (password: string, code: string) =>
  client.post('/api/auth/totp/disable', { password, code }).then((r) => r.data);

export const regenerateBackupCodes = (password: string) =>
  client
    .post<{ ok: boolean; backup_codes: string[] }>('/api/auth/totp/backup-codes', { password })
    .then((r) => r.data);
