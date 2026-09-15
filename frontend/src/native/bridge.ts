/**
 * Android WebView bridge helpers.
 * window.DietDiaryNative is injected by the native app.
 */

declare global {
  interface Window {
    DietDiaryNative?: {
      getInfo(): string;           // JSON { platform, appVersion, deviceId }
      scanBarcode(): void;         // fires CustomEvent 'dd:barcode' with detail { code, format }
      share(title: string, text: string, imageBase64OrNull: string | null): void;
      registerDevice(): void;
      getNotificationStatus(): string;  // JSON { enabled }
      notify(title: string, body: string): void;
      checkInboxNow(): void;
      getRealtimeNotifications?(): string;  // JSON { enabled: boolean }
      setRealtimeNotifications?(enabled: boolean): void;
      // v1.2 新增
      takePhoto?(): void;
      pickPhoto?(): void;
      getPendingUpload?(): string;      // JSON { image_path, image_url, ts } or ""
      clearPendingUpload?(): void;
      getBatteryStatus?(): string;      // JSON { ignoring: boolean }
      requestIgnoreBatteryOptimizations?(): void;
      setBadge?(count: number): void;
    };
  }
}

export interface NativeInfo {
  platform: string;
  appVersion: string;
  deviceId: string;
}

export interface PendingUpload {
  image_path: string;
  image_url: string;
  ts?: number;
}

export interface BatteryStatus {
  ignoring: boolean;
}

export function isNativeApp(): boolean {
  return /DietDiaryApp\//.test(navigator.userAgent) || typeof window.DietDiaryNative !== 'undefined';
}

export function nativeInfo(): NativeInfo | null {
  try {
    if (window.DietDiaryNative?.getInfo) {
      return JSON.parse(window.DietDiaryNative.getInfo()) as NativeInfo;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function scanBarcodeNative(): Promise<string | null> {
  return new Promise((resolve) => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ code: string | null; format: string }>).detail;
      window.removeEventListener('dd:barcode', handler);
      clearTimeout(timer);
      resolve(detail.code ?? null);
    };
    window.addEventListener('dd:barcode', handler);
    const timer = setTimeout(() => {
      window.removeEventListener('dd:barcode', handler);
      resolve(null);
    }, 60000);
    try {
      window.DietDiaryNative?.scanBarcode();
    } catch {
      window.removeEventListener('dd:barcode', handler);
      clearTimeout(timer);
      resolve(null);
    }
  });
}

export function nativeShare(title: string, text: string, dataUrl?: string): void {
  try {
    window.DietDiaryNative?.share(title, text, dataUrl ?? null);
  } catch {
    /* ignore */
  }
}

export function registerDeviceNative(): void {
  try {
    window.DietDiaryNative?.registerDevice();
  } catch {
    /* ignore */
  }
}

// ---------- v1.2 helpers ----------

export function nativeTakePhoto(): void {
  try {
    window.DietDiaryNative?.takePhoto?.();
  } catch {
    /* ignore */
  }
}

export function nativePickPhoto(): void {
  try {
    window.DietDiaryNative?.pickPhoto?.();
  } catch {
    /* ignore */
  }
}

export function getPendingUploadNative(): PendingUpload | null {
  try {
    const raw = window.DietDiaryNative?.getPendingUpload?.();
    if (raw && raw.trim()) {
      return JSON.parse(raw) as PendingUpload;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function clearPendingUploadNative(): void {
  try {
    window.DietDiaryNative?.clearPendingUpload?.();
  } catch {
    /* ignore */
  }
}

export function getBatteryStatusNative(): BatteryStatus | null {
  try {
    const raw = window.DietDiaryNative?.getBatteryStatus?.();
    if (raw && raw.trim()) {
      return JSON.parse(raw) as BatteryStatus;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function requestIgnoreBatteryNative(): void {
  try {
    window.DietDiaryNative?.requestIgnoreBatteryOptimizations?.();
  } catch {
    /* ignore */
  }
}

export function setBadgeNative(n: number): void {
  try {
    window.DietDiaryNative?.setBadge?.(n);
  } catch {
    /* ignore */
  }
}
