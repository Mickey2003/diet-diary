import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

export type ThemeMode = 'light' | 'dark' | 'system';
export type ResolvedMode = 'light' | 'dark';

export interface AppTheme {
  mode: ThemeMode;
  resolved: ResolvedMode;
  primary: string;
  compact: boolean;
  setMode: (m: ThemeMode) => void;
  setPrimary: (c: string) => void;
  setCompact: (v: boolean) => void;
}

const ThemeContext = createContext<AppTheme | null>(null);

const LS_KEY = 'dd-theme';
export const DEFAULT_PRIMARY = '#f5a623';

function loadStored(): { mode: ThemeMode; primary: string; compact: boolean } {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        mode: parsed.mode ?? 'system',
        primary: parsed.primary ?? DEFAULT_PRIMARY,
        compact: parsed.compact ?? false,
      };
    }
  } catch { /* ignore */ }
  return { mode: 'system', primary: DEFAULT_PRIMARY, compact: false };
}

function getSystemTheme(): ResolvedMode {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const stored = loadStored();
  const [mode, setModeState] = useState<ThemeMode>(stored.mode);
  const [primary, setPrimaryState] = useState(stored.primary);
  const [compact, setCompactState] = useState(stored.compact);
  const [systemTheme, setSystemTheme] = useState<ResolvedMode>(getSystemTheme);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setSystemTheme(e.matches ? 'dark' : 'light');
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const resolved: ResolvedMode = mode === 'system' ? systemTheme : mode;

  function save(m: ThemeMode, p: string, c: boolean) {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ mode: m, primary: p, compact: c }));
    } catch { /* ignore */ }
  }

  function setMode(m: ThemeMode) { setModeState(m); save(m, primary, compact); }
  function setPrimary(p: string) { setPrimaryState(p); save(mode, p, compact); }
  function setCompact(c: boolean) { setCompactState(c); save(mode, primary, c); }

  return (
    <ThemeContext.Provider value={{ mode, resolved, primary, compact, setMode, setPrimary, setCompact }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useAppTheme(): AppTheme {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useAppTheme must be used within ThemeProvider');
  return ctx;
}
