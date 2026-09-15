# 饮食日记 Android 客户端

## 简介

这是一个轻量 WebView 外壳应用。所有业务逻辑都运行在你自己的服务器上，客户端只负责：

- 用 WebView 加载服务器页面，提供接近原生的体验
- 通过 `window.DietDiaryNative` 桥接扫码、分享、下载等原生功能
- 在后台定期轮询服务器收件箱并推送通知

服务器端更新后，所有用户无需升级 APK 即可获得新功能。

---

## 本地构建

**前提条件**：Android Studio（含内置 JDK 17）或独立 JDK 17 + Android SDK。

```bash
cd android
./gradlew assembleDebug
# APK 位置: app/build/outputs/apk/debug/app-debug.apk
```

正式签名包：
```bash
export KEYSTORE_FILE=/path/to/keystore.jks
export KEYSTORE_PASSWORD=xxx
export KEY_ALIAS=xxx
export KEY_PASSWORD=xxx
./gradlew assembleRelease
# APK 位置: app/build/outputs/apk/release/app-release.apk
```

---

## CI 构建 & 下载 APK

每次向 `android/**` 路径推送代码时，GitHub Actions 会自动触发构建。

1. 在 GitHub 仓库页面点击 **Actions** → 选择最新的 **Android CI** 工作流
2. 点击工作流运行记录，在 **Artifacts** 区域下载 `diet-diary-apks.zip`
3. 解压后得到 `app-debug.apk`（调试包）和 `app-release.apk`（发布包）

如需签名发布包，在仓库 Settings → Secrets 中添加以下密钥：

| Secret 名称 | 说明 |
|---|---|
| `KEYSTORE_BASE64` | Keystore 文件的 Base64 编码（`base64 keystore.jks`） |
| `KEYSTORE_PASSWORD` | Keystore 密码 |
| `KEY_ALIAS` | 密钥别名 |
| `KEY_PASSWORD` | 密钥密码 |

未设置这些密钥时，发布包会使用调试签名（可安装，不可上架应用商店）。

---

## 安装

1. 在 Android 手机的 **设置 → 安全** 中开启"允许安装未知来源应用"（或针对文件管理器开启）
2. 将 APK 传输到手机，用文件管理器点击安装
3. 如遇"未知来源"提示，选择"仍然安装"

---

## 首次启动 & 服务器配置

1. 打开应用，进入服务器地址设置页
2. 输入服务器地址，如 `https://your.server.com` 或 `http://192.168.1.10:8000`
3. 点击 **测试连接** 确认服务器可达
4. 点击 **保存并继续** 进入主界面

---

## 自签名证书

如果服务器使用自签名 SSL 证书（例如使用 Caddy 的 `tls internal`）：

- 测试连接时会弹出"证书不受信任"对话框
- 点击 **继续** 后，应用会记住该主机名并允许后续连接
- 此信任记录保存在本地，重新安装应用后需要重新确认

---

## 通知权限 & 国产 ROM 白名单

应用首次成功加载服务器页面并检测到登录 Cookie 后，会请求通知权限（Android 13+）。

**通知收不到？** 国产手机（小米 / 华为 / OPPO / vivo 等）可能在后台杀死应用进程。解决方法：

1. 打开菜单 → **通知设置帮助**，点击"打开应用设置"
2. 在应用设置中：
   - 开启 **自启动**
   - 开启 **后台运行**
   - 电池优化 → 设为 **不限制**

---

## 菜单说明

点击右上角 **⋮** 打开菜单：

| 菜单项 | 功能 |
|---|---|
| 刷新 | 重新加载当前页面 |
| 立即检查通知 | 立即轮询服务器收件箱 |
| 通知设置帮助 | 显示国产 ROM 白名单配置指南 |
| 更换服务器 | 重新配置服务器地址 |
| 清除缓存与登录 | 清除所有本地数据和登录状态 |
| 关于 | 显示版本号和服务器地址 |

---

## 故障排查

| 现象 | 可能原因 | 解决方法 |
|---|---|---|
| 页面一直显示"无法连接" | 服务器未启动或地址错误 | 检查服务器状态；重新设置地址 |
| SSL 证书错误循环弹窗 | 证书主机名与地址不匹配 | 在对话框中点击"继续"并记住该主机 |
| 收不到通知 | 后台进程被杀 | 参考上方"国产 ROM 白名单"步骤 |
| 相册/相机无法选取图片 | 相机权限未授予 | 在系统设置中授予相机权限 |
| 下载没有进度/找不到文件 | 外部存储权限问题 | 在系统下载管理器中查看 |
