/**
 * 前台就餐提醒调度器。
 * 每 30s 检查活跃餐单今日餐次，在餐次时间（减去 lead_minutes）的 [t, t+2min) 窗口内播放提醒音。
 * 同时每 60s 检查收件箱中的 meal_alert 消息，对尚未播放的消息播放音效。
 */
import { createElement, useCallback, useEffect, useRef } from 'react';
import { Button } from 'antd';
import type { NotificationInstance } from 'antd/es/notification/interface';
import { listPlans, getTodayMeals } from '../api/health';
import { getAlertSettings } from '../api/sounds';
import client from '../api/client';

const CACHE_KEY = 'dd-today-meals-cache';
const FIRED_KEY = 'dd-meal-alert-fired';
const AUDIO_UNLOCKED_KEY = 'dd-audio-unlocked';
const CACHE_TTL_MS = 10 * 60 * 1000; // 10 min

interface TodayCache {
  date: string;
  fetchedAt: number;
  meals: { meal_type: string; time: string; dishes: { name: string }[] }[];
}

interface InboxMsg {
  id: number;
  kind: string;
  created_at: string;
  extra?: {
    sound_url?: string;
    meal_type?: string;
    time?: string;
  };
}

let sharedAudio: HTMLAudioElement | null = null;

function getAudio(): HTMLAudioElement {
  if (!sharedAudio) sharedAudio = new Audio();
  return sharedAudio;
}

function primeAudio() {
  try {
    const a = getAudio();
    a.muted = true;
    const p = a.play();
    if (p) p.then(() => { a.pause(); a.muted = false; }).catch(() => {});
    localStorage.setItem(AUDIO_UNLOCKED_KEY, '1');
  } catch { /* ignore */ }
}

function playSound(url: string, volume: number) {
  try {
    const a = getAudio();
    a.pause();
    a.src = url;
    a.volume = Math.min(1, Math.max(0, volume));
    const p = a.play();
    if (p) p.catch(() => { /* autoplay blocked — show visual only */ });
  } catch { /* ignore */ }
}

function getFiredSet(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(FIRED_KEY) ?? '[]') as string[]);
  } catch { return new Set(); }
}

function addFired(key: string) {
  try {
    const s = getFiredSet();
    s.add(key);
    // Keep at most 500 entries to avoid bloat
    const arr = [...s].slice(-500);
    localStorage.setItem(FIRED_KEY, JSON.stringify(arr));
  } catch { /* ignore */ }
}

export function useMealAlerts(
  notificationApi: NotificationInstance,
  navigate: (path: string) => void,
) {
  const inboxLatestIdRef = useRef<number>(0);

  // Unlock audio on first user interaction
  useEffect(() => {
    if (localStorage.getItem(AUDIO_UNLOCKED_KEY)) return;
    const handle = () => {
      primeAudio();
      document.removeEventListener('click', handle);
      document.removeEventListener('touchstart', handle);
    };
    document.addEventListener('click', handle, { passive: true });
    document.addEventListener('touchstart', handle, { passive: true });
    return () => {
      document.removeEventListener('click', handle);
      document.removeEventListener('touchstart', handle);
    };
  }, []);

  const checkScheduled = useCallback(async () => {
    try {
      const settings = await getAlertSettings();
      if (!settings.enabled) return;

      const todayStr = new Date().toISOString().split('T')[0];

      // Cache today's meals
      let meals: TodayCache['meals'] | null = null;
      try {
        const raw = localStorage.getItem(CACHE_KEY);
        if (raw) {
          const c = JSON.parse(raw) as TodayCache;
          if (c.date === todayStr && Date.now() - c.fetchedAt < CACHE_TTL_MS) {
            meals = c.meals;
          }
        }
      } catch { /* ignore */ }

      if (!meals) {
        const plans = await listPlans();
        const active = plans.find((p) => p.is_active);
        if (!active) return;
        const today = await getTodayMeals(active.id);
        meals = today.meals ?? [];
        try {
          const cache: TodayCache = {
            date: todayStr,
            fetchedAt: Date.now(),
            meals,
          };
          localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
        } catch { /* ignore */ }
      }

      const now = new Date();
      const nowMin = now.getHours() * 60 + now.getMinutes();
      const leadMin = settings.lead_minutes ?? 0;
      const allowedTypes = settings.meal_types ?? [];
      const firedSet = getFiredSet();

      for (const meal of meals) {
        if (allowedTypes.length > 0 && !allowedTypes.includes(meal.meal_type)) continue;
        const [hStr, mStr] = (meal.time ?? '').split(':');
        const h = parseInt(hStr ?? '0', 10);
        const m = parseInt(mStr ?? '0', 10);
        if (isNaN(h) || isNaN(m)) continue;
        const triggerMin = h * 60 + m - leadMin;
        if (nowMin < triggerMin || nowMin >= triggerMin + 2) continue;

        const key = `${todayStr}|${meal.meal_type}|${meal.time}`;
        if (firedSet.has(key)) continue;
        addFired(key);

        if (settings.sound_url) playSound(settings.sound_url, settings.volume ?? 0.8);

        const dishNames = meal.dishes?.map((d) => d.name).join('、') ?? '';
        notificationApi.open({
          message: `到${meal.meal_type}时间了`,
          description: dishNames || '按计划用餐',
          duration: 10,
          key,
          btn: createElement(
            Button,
            { type: 'link', size: 'small', onClick: () => navigate('/health?tab=plans') },
            '查看餐单',
          ),
        });
      }
    } catch { /* ignore silently */ }
  }, [notificationApi, navigate]);

  const checkInboxAlerts = useCallback(async () => {
    try {
      const settings = await getAlertSettings();
      if (!settings.enabled) return;

      const res = await client.get<{ messages: InboxMsg[] }>('/api/notify/inbox', {
        params: { since_id: inboxLatestIdRef.current, limit: 20 },
      });
      const msgs = res.data.messages ?? [];
      if (msgs.length > 0) {
        inboxLatestIdRef.current = Math.max(...msgs.map((m) => m.id));
      }

      const firedSet = getFiredSet();
      for (const msg of msgs) {
        if (msg.kind !== 'meal_alert') continue;
        const soundUrl = msg.extra?.sound_url;
        if (!soundUrl) continue;
        const mealType = msg.extra?.meal_type ?? 'meal';
        const time = msg.extra?.time ?? '';
        const dateStr = new Date(msg.created_at).toISOString().split('T')[0];
        const key = `${dateStr}|${mealType}|${time}`;
        if (firedSet.has(key)) continue;
        addFired(key);
        playSound(soundUrl, settings.volume ?? 0.8);
      }
    } catch { /* ignore silently */ }
  }, []);

  useEffect(() => {
    // Initial check
    checkScheduled();
    checkInboxAlerts();

    const schedTimer = setInterval(() => {
      if (!document.hidden) checkScheduled();
    }, 30000);

    const inboxTimer = setInterval(() => {
      if (!document.hidden) checkInboxAlerts();
    }, 60000);

    const handleVisibility = () => {
      if (!document.hidden) {
        checkScheduled();
        checkInboxAlerts();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      clearInterval(schedTimer);
      clearInterval(inboxTimer);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [checkScheduled, checkInboxAlerts]);
}
