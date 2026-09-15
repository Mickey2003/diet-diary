import { useEffect, useState } from 'react';
import { getPendingTasks, type PendingTasks } from '../api/endpoints';

const EMPTY: PendingTasks = {
  plan: false,
  slot: false,
  report: false,
  query: false,
  share: false,
  vision: false,
  memory: false,
};

/**
 * 读取服务端“当前用户正在进行的任务”，用于页面刷新后恢复加载态，
 * 避免用户以为没在跑而重复点击。
 */
export function usePendingTasks(): PendingTasks {
  const [pending, setPending] = useState<PendingTasks>(EMPTY);

  useEffect(() => {
    let alive = true;
    getPendingTasks()
      .then((p) => { if (alive) setPending(p); })
      .catch(() => { /* ignore */ });
    return () => { alive = false; };
  }, []);

  return pending;
}

/** 轮询直到某任务结束（用于刷新后恢复等待） */
export function pollUntilDone(task: keyof PendingTasks, onDone: () => void, intervalMs = 4000): () => void {
  const timer = setInterval(async () => {
    try {
      const p = await getPendingTasks();
      if (!p[task]) {
        clearInterval(timer);
        onDone();
      }
    } catch {
      /* ignore */
    }
  }, intervalMs);
  return () => clearInterval(timer);
}
