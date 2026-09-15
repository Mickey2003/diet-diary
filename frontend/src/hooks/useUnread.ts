import { useCallback, useEffect, useRef, useState } from 'react';
import client from '../api/client';

interface UnreadOut {
  unread: number;
  latest_id: number;
}

export function useUnread() {
  const [unread, setUnread] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await client.get<UnreadOut>('/api/notify/unread');
      setUnread(res.data.unread ?? 0);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    refresh();

    // Poll every 60 seconds while tab is visible
    timerRef.current = setInterval(() => {
      if (!document.hidden) {
        refresh();
      }
    }, 60000);

    // Refresh on visibility change (tab becomes visible)
    const handleVisibility = () => {
      if (!document.hidden) {
        refresh();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [refresh]);

  return { unread, refresh };
}
