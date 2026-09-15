# DietDiaryNative JS Bridge

The Android app exposes a global object `window.DietDiaryNative` to the web app loaded inside the WebView.

**Security**: every method (except `reload`) verifies that the currently loaded URL belongs to the configured server host before acting. Methods called from external origins or the offline error page silently no-op.

---

## Detection

Use the User-Agent suffix to detect the app shell:

```js
const isApp = navigator.userAgent.includes('DietDiaryApp/');
const isAndroid = navigator.userAgent.includes('DietDiaryApp/') && navigator.userAgent.includes('Android');
```

Then guard all bridge calls:

```js
if (window.DietDiaryNative) {
    DietDiaryNative.registerDevice();
}
```

---

## Methods

### `getInfo() → string (JSON)`

Returns device/app metadata.

```js
const info = JSON.parse(DietDiaryNative.getInfo());
// { platform: "android", appVersion: "1.0.0", deviceId: "<uuid>" }
```

---

### `scanBarcode()`

Opens the native barcode scanner. The result is delivered asynchronously via a `dd:barcode` CustomEvent on `window`.

```js
window.addEventListener('dd:barcode', (e) => {
    const { code, format } = e.detail;
    if (code !== null) {
        console.log(`Scanned ${format}: ${code}`);
    } else {
        console.log('Scan cancelled');
    }
});
DietDiaryNative.scanBarcode();
```

Supported formats: `EAN_13`, `EAN_8`, `UPC_A`, `UPC_E`, `CODE_128`, `QR_CODE`.

---

### `share(title, text, imageBase64?)`

Opens the system share sheet.

| Param | Type | Description |
|---|---|---|
| `title` | string | Share title / subject |
| `text` | string | Text payload |
| `imageBase64` | string \| null | PNG image as Base64 (without data URI prefix). When provided the image is shared as a file attachment alongside the text. |

```js
DietDiaryNative.share('My meal', 'Breakfast today', null);
// or with image:
DietDiaryNative.share('My meal', '', base64PngString);
```

---

### `openExternal(url)`

Opens a URL in the system browser.

```js
DietDiaryNative.openExternal('https://example.com');
```

---

### `setServerUrl(url)`

Navigates the app to the server-change setup screen. The `url` parameter is currently unused (the user re-enters it).

```js
DietDiaryNative.setServerUrl('');
```

---

### `notify(title, body)`

Posts a local notification immediately, without going through the server inbox. Useful for foreground alerts.

```js
DietDiaryNative.notify('餐后提醒', '别忘了记录今天的晚餐！');
```

---

### `getNotificationStatus() → string (JSON)`

```js
const status = JSON.parse(DietDiaryNative.getNotificationStatus());
// { enabled: true }
```

---

### `registerDevice()`

Registers this device with the server's push notification endpoint (`POST /api/notify/devices`). Call this after the user logs in so the server can address notifications to this device.

```js
DietDiaryNative.registerDevice();
```

---

### `reload()`

Navigates back to the server URL. This method is intentionally exempt from the host check so the offline error page can call it.

```js
DietDiaryNative.reload();
```

---

### `checkInboxNow()`

Triggers an immediate inbox poll (equivalent to the "立即检查通知" menu item).

```js
DietDiaryNative.checkInboxNow();
```

---

## `dd:barcode` CustomEvent

Fired on `window` after `scanBarcode()` completes.

```ts
interface BarcodeDetail {
    code: string | null;   // null on cancel
    format: string | null; // e.g. "EAN_13", "QR_CODE", null on cancel
}
```

---

## Recommended integration pattern

```js
(function () {
    if (!window.DietDiaryNative) return;

    // 1. Register device after login
    document.addEventListener('app:login', () => {
        DietDiaryNative.registerDevice();
    });

    // 2. Prefer native share when available
    window.nativeShare = (title, text, imageBase64 = null) => {
        if (window.DietDiaryNative) {
            DietDiaryNative.share(title, text, imageBase64);
        } else if (navigator.share) {
            navigator.share({ title, text });
        }
    };

    // 3. Listen for barcode events globally
    window.addEventListener('dd:barcode', (e) => {
        const { code, format } = e.detail;
        if (code) window.dispatchEvent(new CustomEvent('barcode:result', { detail: { code, format } }));
    });
})();
```

## v1.1 新增

| 方法 | 说明 |
|---|---|
| `setRealtimeNotifications(enabled: boolean)` | 开/关"实时通知"前台服务（长轮询 `/api/notify/inbox?wait=25`，新消息秒级到达）。关闭后退回 WorkManager 每 15 分钟轮询。 |
| `getRealtimeNotifications(): boolean` | 当前是否开启实时通知。 |

修复：所有桥方法不再在 JS 线程访问 `webView.url`（会抛异常导致调用静默失败），改为由 Activity 在 UI 线程维护当前 URL。

## v1.2 新增（原生拍照直传 / 草稿恢复 / 电池优化 / 角标）

| 方法 | 说明 |
|---|---|
| `takePhoto()` | 调用系统相机拍照。原生端拍完后**直接上传**到 `POST /api/meals/upload-only`（带登录 Cookie），成功后向页面派发 `dd:photo` 事件：`detail = {image_path, image_url}`；同时把结果写入本地"待处理上传"，即使页面因内存回收被重载也不会丢。 |
| `pickPhoto()` | 从相册选择，流程同上。 |
| `getPendingUpload(): string` | 返回上一次原生上传但页面尚未消费的结果 JSON（`{"image_path":..,"image_url":..,"ts":..}`），没有则返回空字符串。页面加载时应调用一次以恢复草稿。 |
| `clearPendingUpload()` | 页面消费（识别/保存/放弃）后清除。 |
| `getBatteryStatus(): string` | `{"ignoring": true/false}` —— 是否已忽略电池优化（false 时后台通知可能被系统杀掉，建议在页面展示提示）。 |
| `requestIgnoreBatteryOptimizations()` | 弹出系统"忽略电池优化"对话框。 |
| `setBadge(count: number)` | 设置桌面图标角标数（依赖启动器支持：MIUI/EMUI/ColorOS/三星/Nova 等）。0 清除。 |

行为变化：
- App 不再在解锁/切回时重新加载网页；Activity 重建时用 `WebView.restoreState` 恢复。
- 网页侧应把"记录一餐"的草稿（image_path、识别结果、已编辑菜品）存到 `localStorage`，重载后自动恢复。
- 识别已上传图片请用 `POST /api/meals/recognize-path {image_path}`。
- 默认服务器地址预填 `https://diet-diary.720172.xyz`，可手动更改。

## v1.3 新增（就餐提醒音效）

- `WebView.settings.mediaPlaybackRequiresUserGesture = false`：网页在 App 内可直接 `new Audio(url).play()` 播放提醒音效，无需先点击页面。
- `InboxService`（长轮询）与 `InboxWorker`（15 分钟兜底）收到 `kind == "meal_alert"` 且 `extra.sound_url` 非空的收件箱消息时，除弹系统通知外，还会通过 `SoundPlayer.playFromServer()` 用 MediaPlayer 流式播放该音频（带登录 Cookie；`extra.volume` 0–1，`extra.vibrate` 控制震动）。音频地址为服务器相对路径，例如 `/api/sounds/preset/chime` 或 `/api/sounds/file/12`。
- User-Agent 后缀升级为 `DietDiaryApp/1.3 (Android)`；versionCode 4。
- 网页端无需任何改动即兼容旧版 App：旧版仅在页面前台时由网页自己播放。

## v1.3.1

- 文件选择器按 `<input accept>` 类型区分：`audio/*`（上传提醒音效）等非图片类型直接打开系统对应文件选择器，不再弹出“拍照 / 相册”只让选图片。
