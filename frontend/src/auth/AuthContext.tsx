import { createContext, useContext, useCallback, useState, useEffect, type ReactNode } from 'react';
import { getAuthStatus } from '../api/auth';

export interface AuthContextValue {
  username: string;
  displayName: string;
  isAdmin: boolean;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({
  initialUsername,
  initialDisplayName,
  initialIsAdmin,
  children,
}: {
  initialUsername: string;
  initialDisplayName: string;
  initialIsAdmin: boolean;
  children: ReactNode;
}) {
  const [username, setUsername] = useState(initialUsername);
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [isAdmin, setIsAdmin] = useState(initialIsAdmin);

  const refresh = useCallback(async () => {
    try {
      const s = await getAuthStatus();
      if (s.authenticated && s.username) {
        setUsername(s.username);
        setDisplayName(s.display_name ?? s.username);
        setIsAdmin(!!s.is_admin);
      }
    } catch {
      /* ignore */
    }
  }, []);

  // Keep in sync if status changes (e.g. admin toggled by another session)
  useEffect(() => {
    setUsername(initialUsername);
    setDisplayName(initialDisplayName);
    setIsAdmin(initialIsAdmin);
  }, [initialUsername, initialDisplayName, initialIsAdmin]);

  return (
    <AuthContext.Provider value={{ username, displayName, isAdmin, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
