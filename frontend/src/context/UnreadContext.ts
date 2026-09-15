import { createContext } from 'react';

export interface UnreadContextValue {
  unread: number;
  refresh: () => void;
}

export const UnreadContext = createContext<UnreadContextValue | null>(null);
