import client from './client';

export interface TokenOut {
  id: number;
  name: string;
  prefix: string;
  scopes: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

export interface TokenCreated extends TokenOut {
  token: string;
}

export interface TokenCreate {
  name: string;
  scopes: 'all' | 'read' | 'mcp' | 'app';
  expires_days?: number;
}

export const listTokens = () =>
  client.get<TokenOut[]>('/api/tokens').then((r) => r.data);

export const createToken = (payload: TokenCreate) =>
  client.post<TokenCreated>('/api/tokens', payload).then((r) => r.data);

export const revokeToken = (id: number) =>
  client.delete(`/api/tokens/${id}`).then((r) => r.data);
