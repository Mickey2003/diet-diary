package com.dietdiary.app

import android.app.Activity
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.activity.result.ActivityResult
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.URL

/**
 * 暴露给网页的 `window.DietDiaryNative`。
 *
 * 安全：除 reload() 外，所有方法都校验当前页面属于配置的服务器主机。
 * 线程：@JavascriptInterface 方法运行在 JS 线程，任何 UI / WebView 操作都必须 handler.post。
 */
class WebAppInterface(
    private val mainActivity: MainActivity,
    private val webView: WebView
) {

    private val context: Context get() = mainActivity.applicationContext
    private val handler = Handler(Looper.getMainLooper())

    /** 当前页面 URL，由 MainActivity 在 UI 线程维护（不能在 JS 线程读 webView.url）。 */
    @Volatile
    var currentUrl: String? = null

    private fun isServerHost(): Boolean {
        val url = currentUrl ?: return false
        val serverUrl = Prefs.getServerUrl(context) ?: return false
        return try {
            URL(url).host == URL(serverUrl).host
        } catch (_: Exception) {
            false
        }
    }

    // ── 基础 ─────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun getInfo(): String {
        if (!isServerHost()) return "{}"
        return JSONObject().apply {
            put("platform", "android")
            put("appVersion", BuildConfig.VERSION_NAME)
            put("deviceId", Prefs.getDeviceId(context))
        }.toString()
    }

    @JavascriptInterface
    fun reload() {
        handler.post {
            val serverUrl = Prefs.getServerUrl(context) ?: return@post
            val current = webView.url ?: ""
            val onServer = try {
                current.isNotEmpty() && !current.startsWith("file:") && URL(current).host == URL(serverUrl).host
            } catch (_: Exception) { false }
            if (onServer) webView.reload() else webView.loadUrl(serverUrl)
        }
    }

    @JavascriptInterface
    fun openExternal(url: String) {
        if (!isServerHost()) return
        handler.post {
            try { mainActivity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } catch (_: Exception) {}
        }
    }

    @JavascriptInterface
    fun setServerUrl(@Suppress("UNUSED_PARAMETER") url: String) {
        if (!isServerHost()) return
        handler.post {
            mainActivity.startActivity(Intent(mainActivity, SetupActivity::class.java).apply {
                putExtra("change_server", true)
            })
        }
    }

    // ── 扫码 ─────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun scanBarcode() {
        if (!isServerHost()) return
        handler.post { mainActivity.startScan() }
    }

    fun handleScanResult(result: ActivityResult) {
        val js = if (result.resultCode == Activity.RESULT_OK) {
            val code = result.data?.getStringExtra("code")
            val format = result.data?.getStringExtra("format") ?: ""
            if (code != null) {
                val safe = code.replace("\\", "\\\\").replace("\"", "\\\"")
                """window.dispatchEvent(new CustomEvent('dd:barcode',{detail:{code:"$safe",format:"$format"}}))"""
            } else {
                """window.dispatchEvent(new CustomEvent('dd:barcode',{detail:{code:null,format:null}}))"""
            }
        } else {
            """window.dispatchEvent(new CustomEvent('dd:barcode',{detail:{code:null,format:null}}))"""
        }
        handler.post { webView.evaluateJavascript(js, null) }
    }

    // ── 原生拍照 / 相册 → 直接上传 ───────────────────────────────────────────

    @JavascriptInterface
    fun takePhoto() {
        if (!isServerHost()) return
        handler.post { mainActivity.startNativePhoto(camera = true) }
    }

    @JavascriptInterface
    fun pickPhoto() {
        if (!isServerHost()) return
        handler.post { mainActivity.startNativePhoto(camera = false) }
    }

    @JavascriptInterface
    fun getPendingUpload(): String {
        if (!isServerHost()) return ""
        return Prefs.getPendingUpload(context)
    }

    @JavascriptInterface
    fun clearPendingUpload() {
        if (!isServerHost()) return
        Prefs.setPendingUpload(context, null)
    }

    /** 上传完成后由 MainActivity 调用：写入待处理结果并通知页面。 */
    fun dispatchPhotoUploaded(json: JSONObject) {
        Prefs.setPendingUpload(context, json.toString())
        val js = "window.dispatchEvent(new CustomEvent('dd:photo',{detail:$json}))"
        handler.post { webView.evaluateJavascript(js, null) }
    }

    fun dispatchPhotoFailed(reason: String) {
        val safe = reason.replace("\\", "\\\\").replace("\"", "\\\"")
        val js = """window.dispatchEvent(new CustomEvent('dd:photo',{detail:{error:"$safe"}}))"""
        handler.post { webView.evaluateJavascript(js, null) }
    }

    // ── 分享 ─────────────────────────────────────────────────────────────────

    @JavascriptInterface
    fun share(title: String, text: String, imageBase64: String?) {
        if (!isServerHost()) return
        handler.post {
            val intent = Intent(Intent.ACTION_SEND)
            if (!imageBase64.isNullOrBlank()) {
                try {
                    // 网页传进来的是 data URL（data:image/png;base64,xxx），必须先去掉前缀
                    val raw = if (imageBase64.contains(",")) imageBase64.substringAfter(",") else imageBase64
                    val bytes = Base64.decode(raw, Base64.DEFAULT)
                    val dir = File(mainActivity.cacheDir, "shared_images").apply { mkdirs() }
                    val file = File(dir, "share_${System.currentTimeMillis()}.png")
                    file.writeBytes(bytes)
                    val uri = FileProvider.getUriForFile(mainActivity, "${mainActivity.packageName}.fileprovider", file)
                    intent.type = "image/png"
                    intent.putExtra(Intent.EXTRA_STREAM, uri)
                    intent.putExtra(Intent.EXTRA_TEXT, text)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    // 部分应用只认 ClipData，这里一并设置并授予读取权限
                    intent.clipData = ClipData.newUri(mainActivity.contentResolver, "image", uri)
                } catch (_: Exception) {
                    intent.type = "text/plain"
                    intent.putExtra(Intent.EXTRA_TEXT, text)
                }
            } else {
                intent.type = "text/plain"
                intent.putExtra(Intent.EXTRA_TEXT, text)
            }
            intent.putExtra(Intent.EXTRA_TITLE, title)
            intent.putExtra(Intent.EXTRA_SUBJECT, title)
            mainActivity.startActivity(Intent.createChooser(intent, mainActivity.getString(R.string.share_chooser_title)))
        }
    }

    // ── 通知 / 设备 ──────────────────────────────────────────────────────────

    @JavascriptInterface
    fun notify(title: String, body: String) {
        if (!isServerHost()) return
        Notifier.post(context, (System.currentTimeMillis() and 0x7FFFFFFF).toInt(), title, body)
    }

    @JavascriptInterface
    fun getNotificationStatus(): String {
        if (!isServerHost()) return """{"enabled":false}"""
        return JSONObject().apply { put("enabled", Notifier.areEnabled(context)) }.toString()
    }

    @JavascriptInterface
    fun registerDevice() {
        if (!isServerHost()) return
        InboxWorker.registerDevice(context)
    }

    @JavascriptInterface
    fun checkInboxNow() {
        if (!isServerHost()) return
        InboxWorker.runOnce(context)
    }

    @JavascriptInterface
    fun setRealtimeNotifications(enabled: Boolean) {
        if (!isServerHost()) return
        Prefs.setRealtimeEnabled(context, enabled)
        handler.post { if (enabled) InboxService.start(context) else InboxService.stop(context) }
    }

    @JavascriptInterface
    fun getRealtimeNotifications(): Boolean = Prefs.isRealtimeEnabled(context)

    // ── 电池优化 / 角标 ──────────────────────────────────────────────────────

    @JavascriptInterface
    fun getBatteryStatus(): String {
        val ignoring = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            (context.getSystemService(Context.POWER_SERVICE) as PowerManager)
                .isIgnoringBatteryOptimizations(context.packageName)
        } else true
        return JSONObject().apply { put("ignoring", ignoring) }.toString()
    }

    @JavascriptInterface
    fun requestIgnoreBatteryOptimizations() {
        if (!isServerHost()) return
        handler.post { mainActivity.requestIgnoreBattery() }
    }

    @JavascriptInterface
    fun setBadge(count: Int) {
        if (!isServerHost()) return
        Notifier.applyBadge(context, count)
    }
}
