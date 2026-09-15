package com.dietdiary.app

import android.Manifest
import android.app.DownloadManager
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.provider.Settings
import android.util.Base64
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.ActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.webkit.WebSettingsCompat
import androidx.webkit.WebViewFeature
import com.dietdiary.app.databinding.ActivityMainBinding
import java.io.File
import java.net.URL

/**
 * Main WebView shell.  Loads the configured server URL and bridges the web app
 * to native Android features via [WebAppInterface] (`window.DietDiaryNative`).
 */
class MainActivity : AppCompatActivity() {

    // ── View binding ──────────────────────────────────────────────────────────

    private lateinit var binding: ActivityMainBinding

    // ── JS bridge ─────────────────────────────────────────────────────────────

    private lateinit var webInterface: WebAppInterface

    // ── State ─────────────────────────────────────────────────────────────────

    private var lastBackPressMs = 0L
    private var registeredThisSession = false

    // File chooser callback (kept while waiting for picker/camera result)
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private var cameraImageUri: Uri? = null

    // ── Activity-result launchers (must be registered before onCreate) ────────

    private val scanLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result: ActivityResult ->
            if (::webInterface.isInitialized) webInterface.handleScanResult(result)
        }

    private val galleryLauncher =
        registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
            fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else emptyArray())
            fileCallback = null
        }

    private val cameraLauncher =
        registerForActivityResult(ActivityResultContracts.TakePicture()) { success: Boolean ->
            val uri = if (success) cameraImageUri else null
            fileCallback?.onReceiveValue(if (uri != null) arrayOf(uri) else emptyArray())
            fileCallback = null
            if (!success) cameraImageUri = null
        }

    private val cameraPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted: Boolean ->
            if (granted) takeCameraPhoto()
            else {
                fileCallback?.onReceiveValue(emptyArray())
                fileCallback = null
            }
        }

    private val notifPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { _ -> }

    // ── 原生拍照 / 相册 → 直接上传（不经过网页的 <input type=file>，Activity 重建也不丢） ──

    private var nativePhotoUri: Uri? = null

    private val nativeCameraLauncher =
        registerForActivityResult(ActivityResultContracts.TakePicture()) { success: Boolean ->
            val uri = nativePhotoUri
            if (success && uri != null) uploadNativePhoto(uri) else notifyPhotoFailed("已取消拍照")
        }

    private val nativeGalleryLauncher =
        registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
            if (uri != null) uploadNativePhoto(uri) else notifyPhotoFailed("未选择照片")
        }

    private val nativeCameraPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted: Boolean ->
            if (granted) launchNativeCamera() else notifyPhotoFailed("未授予相机权限")
        }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Redirect to setup if no server configured
        val serverUrl = Prefs.getServerUrl(this)
        if (serverUrl.isNullOrBlank()) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setSupportActionBar(binding.toolbar)

        Notifier.createChannel(this)
        setupWebView(serverUrl)
        setupSwipeRefresh()
        setupBackPress()

        // 恢复拍照过程中的临时 URI（Activity 可能在相机打开期间被系统回收重建）
        savedInstanceState?.getString("nativePhotoUri")?.let { nativePhotoUri = Uri.parse(it) }
        savedInstanceState?.getString("cameraImageUri")?.let { cameraImageUri = Uri.parse(it) }

        val openUrl = intent.getStringExtra("open_url")
        when {
            !openUrl.isNullOrBlank() -> binding.webView.loadUrl(openUrl)           // 通知点击进入
            savedInstanceState != null && binding.webView.restoreState(savedInstanceState) != null -> Unit  // 重建：恢复而不刷新
            else -> binding.webView.loadUrl(serverUrl)
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::binding.isInitialized) binding.webView.saveState(outState)
        nativePhotoUri?.let { outState.putString("nativePhotoUri", it.toString()) }
        cameraImageUri?.let { outState.putString("cameraImageUri", it.toString()) }
    }

    // ── 原生拍照上传 ─────────────────────────────────────────────────────────

    fun startNativePhoto(camera: Boolean) {
        if (camera) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                launchNativeCamera()
            } else {
                nativeCameraPermLauncher.launch(Manifest.permission.CAMERA)
            }
        } else {
            nativeGalleryLauncher.launch("image/*")
        }
    }

    private fun launchNativeCamera() {
        val dir = externalCacheDir ?: cacheDir
        val file = File(dir, "native_${System.currentTimeMillis()}.jpg")
        try {
            nativePhotoUri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", file)
            nativeCameraLauncher.launch(nativePhotoUri!!)
        } catch (e: Exception) {
            notifyPhotoFailed("无法启动相机：${e.message}")
        }
    }

    private fun uploadNativePhoto(uri: Uri) {
        Toast.makeText(this, R.string.toast_uploading_photo, Toast.LENGTH_SHORT).show()
        Thread {
            try {
                val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: throw IllegalStateException("读取照片失败")
                val server = Prefs.getServerUrl(this) ?: throw IllegalStateException("未配置服务器")
                val cookie = CookieManager.getInstance().getCookie(server) ?: ""
                val resp = Http.postMultipart(this, "$server/api/meals/upload-only", "file", "photo.jpg", bytes,
                    headers = mapOf("Cookie" to cookie))
                if (resp.code != 200) throw IllegalStateException("上传失败（HTTP ${resp.code}）")
                val json = org.json.JSONObject(resp.body)
                json.put("ts", System.currentTimeMillis())
                runOnUiThread {
                    if (::webInterface.isInitialized) webInterface.dispatchPhotoUploaded(json)
                    Toast.makeText(this, R.string.toast_photo_uploaded, Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                notifyPhotoFailed(e.message ?: "上传失败")
            } finally {
                nativePhotoUri = null
            }
        }.start()
    }

    private fun notifyPhotoFailed(reason: String) {
        runOnUiThread {
            if (::webInterface.isInitialized) webInterface.dispatchPhotoFailed(reason)
        }
    }

    // ── 电池优化 ─────────────────────────────────────────────────────────────

    fun requestIgnoreBattery() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:$packageName")
            })
        } catch (_: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {}
        }
    }

    private fun isIgnoringBattery(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(POWER_SERVICE) as android.os.PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun maybeAskBattery() {
        if (isIgnoringBattery() || Prefs.wasBatteryAsked(this)) return
        Prefs.setBatteryAsked(this)
        AlertDialog.Builder(this)
            .setTitle(R.string.battery_dialog_title)
            .setMessage(R.string.battery_dialog_message)
            .setPositiveButton(R.string.battery_dialog_ok) { _, _ -> requestIgnoreBattery() }
            .setNegativeButton(R.string.battery_dialog_later, null)
            .show()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra("open_url")?.takeIf { it.isNotBlank() }
            ?.let { binding.webView.loadUrl(it) }
    }

    override fun onResume() {
        super.onResume()
        InboxWorker.schedule(this)
        InboxWorker.runOnce(this)
        if (Prefs.isRealtimeEnabled(this)) InboxService.start(this)
    }

    override fun onPause() {
        super.onPause()
        CookieManager.getInstance().flush()
    }

    // ── Menu ──────────────────────────────────────────────────────────────────

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean = when (item.itemId) {
        R.id.menu_refresh -> {
            binding.webView.reload(); true
        }
        R.id.menu_check_notifications -> {
            InboxWorker.runOnce(this)
            Toast.makeText(this, R.string.toast_checking_inbox, Toast.LENGTH_SHORT).show()
            true
        }
        R.id.menu_realtime -> {
            val enable = !Prefs.isRealtimeEnabled(this)
            Prefs.setRealtimeEnabled(this, enable)
            if (enable) InboxService.start(this) else InboxService.stop(this)
            Toast.makeText(this, if (enable) R.string.toast_realtime_on else R.string.toast_realtime_off, Toast.LENGTH_SHORT).show()
            true
        }
        R.id.menu_notification_help -> {
            showNotifHelpDialog(); true
        }
        R.id.menu_battery -> {
            if (isIgnoringBattery()) Toast.makeText(this, R.string.toast_battery_ok, Toast.LENGTH_SHORT).show()
            else requestIgnoreBattery()
            true
        }
        R.id.menu_change_server -> {
            startActivity(Intent(this, SetupActivity::class.java).apply {
                putExtra("change_server", true)
            })
            true
        }
        R.id.menu_clear_cache -> {
            showClearCacheDialog(); true
        }
        R.id.menu_about -> {
            showAboutDialog(); true
        }
        else -> super.onOptionsItemSelected(item)
    }

    // ── WebView setup ─────────────────────────────────────────────────────────

    private fun setupWebView(serverUrl: String) {
        val wv = binding.webView
        val settings = wv.settings

        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        @Suppress("DEPRECATION")
        settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        settings.setSupportZoom(false)
        settings.builtInZoomControls = false
        settings.displayZoomControls = false
        settings.mediaPlaybackRequiresUserGesture = false  // 允许网页自动播放提醒音效
        settings.userAgentString = "${settings.userAgentString} DietDiaryApp/1.3 (Android)"

        // 明确关闭 WebView 的算法变暗：网页自己有深浅色主题，系统深色模式下再算法反色会把按钮“抹掉”
        if (WebViewFeature.isFeatureSupported(WebViewFeature.ALGORITHMIC_DARKENING)) {
            WebSettingsCompat.setAlgorithmicDarkeningAllowed(settings, false)
        }

        // Cookies
        val cookieMgr = CookieManager.getInstance()
        cookieMgr.setAcceptCookie(true)
        cookieMgr.setAcceptThirdPartyCookies(wv, true)

        // JS bridge
        webInterface = WebAppInterface(this, wv)
        wv.addJavascriptInterface(webInterface, "DietDiaryNative")

        wv.webViewClient = buildWebViewClient(serverUrl)
        wv.webChromeClient = buildWebChromeClient()

        // Download listener
        wv.setDownloadListener(buildDownloadListener())
    }

    private fun buildWebViewClient(serverUrl: String): WebViewClient {
        val activity = this
        return object : WebViewClient() {

            private fun handleUrl(uri: Uri?): Boolean {
                if (uri == null) return false
                val scheme = uri.scheme?.lowercase() ?: return false
                if (scheme !in listOf("http", "https")) return false   // let WebView handle blob/data/etc

                val serverHost = getServerHost(serverUrl) ?: return false
                return if (uri.host == serverHost) {
                    false   // keep inside WebView
                } else {
                    try { activity.startActivity(Intent(Intent.ACTION_VIEW, uri)) } catch (_: Exception) {}
                    true
                }
            }

            // API 24+
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
                handleUrl(request?.url)

            // API 21–23 回退
            @Suppress("DEPRECATION")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean =
                handleUrl(url?.let { Uri.parse(it) })

            // API 23+ error handler (covers main frame failures)
            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                    request?.isForMainFrame == true
                ) {
                    view?.loadUrl("file:///android_asset/offline.html")
                }
            }

            // Pre-API-23 fallback
            @Suppress("DEPRECATION")
            override fun onReceivedError(
                view: WebView?,
                errorCode: Int,
                description: String?,
                failingUrl: String?
            ) {
                @Suppress("DEPRECATION")
                super.onReceivedError(view, errorCode, description, failingUrl)
                if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
                    view?.loadUrl("file:///android_asset/offline.html")
                }
            }

            override fun onReceivedSslError(
                view: WebView?,
                handler: SslErrorHandler?,
                error: android.net.http.SslError?
            ) {
                val host = try {
                    URL(error?.url ?: "").host
                } catch (_: Exception) { "" }

                if (host.isNotEmpty() && Prefs.isHostTrusted(applicationContext, host)) {
                    handler?.proceed()
                    return
                }

                AlertDialog.Builder(activity)
                    .setTitle(R.string.ssl_dialog_title)
                    .setMessage(R.string.ssl_dialog_message)
                    .setPositiveButton(R.string.ssl_continue) { _, _ ->
                        if (host.isNotEmpty()) Prefs.trustHost(applicationContext, host)
                        handler?.proceed()
                    }
                    .setNegativeButton(R.string.ssl_cancel) { _, _ -> handler?.cancel() }
                    .setOnCancelListener { handler?.cancel() }
                    .show()
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                super.onPageStarted(view, url, favicon)
                webInterface.currentUrl = url
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                webInterface.currentUrl = url
                binding.swipeRefresh.isRefreshing = false

                val serverHost = getServerHost(serverUrl) ?: return
                val pageHost = try { URL(url ?: "").host } catch (_: Exception) { null }

                if (pageHost == serverHost) {
                    val cookie = CookieManager.getInstance().getCookie(url)
                    if (!cookie.isNullOrBlank()) {
                        // Register device once per session
                        if (!registeredThisSession) {
                            registeredThisSession = true
                            InboxWorker.registerDevice(this@MainActivity)
                        }
                        // Ask for notification permission once (Android 13+)
                        if (!Prefs.wasNotifPermissionAsked(this@MainActivity)) {
                            Prefs.setNotifPermissionAsked(this@MainActivity)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                            }
                        } else {
                            // 通知权限之后再引导关闭电池优化（后台通知的关键）
                            maybeAskBattery()
                        }
                    }
                }
            }
        }
    }

    private fun buildWebChromeClient(): WebChromeClient {
        val activity = this
        return object : WebChromeClient() {

            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                super.onProgressChanged(view, newProgress)
                if (newProgress < 100) {
                    binding.progressBar.visibility = View.VISIBLE
                    binding.progressBar.progress = newProgress
                } else {
                    binding.progressBar.visibility = View.GONE
                    binding.swipeRefresh.isRefreshing = false
                }
            }

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                // Cancel any previous callback
                fileCallback?.onReceiveValue(null)
                fileCallback = filePathCallback

                // 非图片类 <input type=file>（例如上传提醒音效 accept="audio/*"）：直接打开对应类型的系统文件选择器
                val accepts = fileChooserParams?.acceptTypes?.filter { it.isNotBlank() } ?: emptyList()
                val wantsImage = accepts.isEmpty() || accepts.any { it.startsWith("image") }
                if (!wantsImage) {
                    val mime = when {
                        accepts.any { it.startsWith("audio") } -> "audio/*"
                        accepts.any { it.startsWith("video") } -> "video/*"
                        accepts.size == 1 && accepts[0].contains("/") -> accepts[0]
                        else -> "*/*"
                    }
                    try {
                        galleryLauncher.launch(mime)
                    } catch (_: Exception) {
                        fileCallback?.onReceiveValue(null)
                        fileCallback = null
                        return false
                    }
                    return true
                }

                AlertDialog.Builder(activity)
                    .setTitle(R.string.file_chooser_title)
                    .setItems(
                        arrayOf(
                            getString(R.string.file_chooser_camera),
                            getString(R.string.file_chooser_gallery)
                        )
                    ) { _, which ->
                        when (which) {
                            0 -> checkCameraAndTakePhoto()
                            1 -> galleryLauncher.launch("image/*")
                        }
                    }
                    .setOnCancelListener {
                        fileCallback?.onReceiveValue(null)
                        fileCallback = null
                    }
                    .show()
                return true
            }
        }
    }

    private fun buildDownloadListener(): DownloadListener {
        return DownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            // 网页用 <a download href="data:image/png;base64,..."> 保存图片，
            // DownloadManager 不支持 data: URI，直接丢给它会抛异常导致闪退，这里单独处理。
            if (url.startsWith("data:")) {
                val filename = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimetype)
                saveDataUrlToGallery(url, filename)
                return@DownloadListener
            }
            val filename = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimetype)
            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setMimeType(mimetype)
                val cookie = CookieManager.getInstance().getCookie(url)
                if (!cookie.isNullOrBlank()) addRequestHeader("Cookie", cookie)
                addRequestHeader("User-Agent", userAgent)
                setTitle(filename)
                setDescription(filename)
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
            }
            (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
            Toast.makeText(this, R.string.toast_download_started, Toast.LENGTH_SHORT).show()
        }
    }

    /**
     * 保存 data: URL（data:image/png;base64,xxx）到相册。
     * 直接把 data: URI 交给 DownloadManager 会抛异常导致闪退，因此这里单独解码保存。
     * Android 10+ 用 MediaStore（无需存储权限）；旧版本写入应用私有 Pictures 目录并通知媒体扫描。
     */
    private fun saveDataUrlToGallery(dataUrl: String, rawFilename: String) {
        try {
            val payload = dataUrl.substringAfter(",", "")
            if (payload.isEmpty()) {
                Toast.makeText(this, R.string.toast_save_failed, Toast.LENGTH_SHORT).show()
                return
            }
            val bytes = Base64.decode(payload, Base64.DEFAULT)
            val filename = if (rawFilename.isBlank() || rawFilename.startsWith("download", true)) {
                "diet-share-${System.currentTimeMillis()}.png"
            } else {
                rawFilename
            }
            val mime = if (filename.endsWith(".jpg", true) || filename.endsWith(".jpeg", true)) {
                "image/jpeg"
            } else {
                "image/png"
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Images.Media.DISPLAY_NAME, filename)
                    put(MediaStore.Images.Media.MIME_TYPE, mime)
                    put(MediaStore.Images.Media.RELATIVE_PATH,
                        Environment.DIRECTORY_PICTURES + "/DietDiary")
                    put(MediaStore.Images.Media.IS_PENDING, 1)
                }
                val uri = contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                if (uri == null) {
                    Toast.makeText(this, R.string.toast_save_failed, Toast.LENGTH_SHORT).show()
                    return
                }
                contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                values.clear()
                values.put(MediaStore.Images.Media.IS_PENDING, 0)
                contentResolver.update(uri, values, null, null)
            } else {
                val dir = getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: run {
                    Toast.makeText(this, R.string.toast_save_failed, Toast.LENGTH_SHORT).show()
                    return
                }
                dir.mkdirs()
                val file = File(dir, filename)
                file.writeBytes(bytes)
                MediaScannerConnection.scanFile(this, arrayOf(file.absolutePath), arrayOf(mime), null)
            }
            Toast.makeText(this, R.string.toast_image_saved, Toast.LENGTH_SHORT).show()
        } catch (_: Exception) {
            Toast.makeText(this, R.string.toast_save_failed, Toast.LENGTH_SHORT).show()
        }
    }

    // ── Camera / gallery helpers ──────────────────────────────────────────────

    private fun checkCameraAndTakePhoto() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED
        ) {
            takeCameraPhoto()
        } else {
            cameraPermLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    private fun takeCameraPhoto() {
        val cacheDir = externalCacheDir ?: run {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
            return
        }
        val file = File(cacheDir, "camera_${System.currentTimeMillis()}.jpg")
        try {
            cameraImageUri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", file)
            cameraLauncher.launch(cameraImageUri!!)
        } catch (e: Exception) {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
        }
    }

    // ── Public for WebAppInterface ────────────────────────────────────────────

    fun startScan() {
        scanLauncher.launch(Intent(this, ScanActivity::class.java))
    }

    // ── SwipeRefresh ──────────────────────────────────────────────────────────

    private fun setupSwipeRefresh() {
        binding.swipeRefresh.setOnRefreshListener {
            binding.webView.reload()
        }
        binding.swipeRefresh.setColorSchemeResources(R.color.colorPrimary)
    }

    // ── Back press ────────────────────────────────────────────────────────────

    private fun setupBackPress() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) {
                    binding.webView.goBack()
                } else {
                    val now = System.currentTimeMillis()
                    if (now - lastBackPressMs < 2_000) {
                        finish()
                    } else {
                        lastBackPressMs = now
                        Toast.makeText(this@MainActivity, R.string.press_back_again, Toast.LENGTH_SHORT).show()
                    }
                }
            }
        })
    }

    // ── Dialogs ───────────────────────────────────────────────────────────────

    private fun showAboutDialog() {
        AlertDialog.Builder(this)
            .setTitle(R.string.about_title)
            .setMessage(
                getString(
                    R.string.about_message,
                    BuildConfig.VERSION_NAME,
                    Prefs.getServerUrl(this) ?: "—"
                )
            )
            .setPositiveButton(R.string.about_ok, null)
            .show()
    }

    private fun showClearCacheDialog() {
        AlertDialog.Builder(this)
            .setTitle(R.string.clear_cache_title)
            .setMessage(R.string.clear_cache_message)
            .setPositiveButton(R.string.clear_cache_ok) { _, _ ->
                binding.webView.clearCache(true)
                binding.webView.clearHistory()
                CookieManager.getInstance().removeAllCookies(null)
                CookieManager.getInstance().flush()
                Prefs.clearAll(this)
                registeredThisSession = false
                val serverUrl = Prefs.getServerUrl(this) ?: return@setPositiveButton
                binding.webView.loadUrl(serverUrl)
            }
            .setNegativeButton(R.string.clear_cache_cancel, null)
            .show()
    }

    private fun showNotifHelpDialog() {
        AlertDialog.Builder(this)
            .setTitle(R.string.notif_help_title)
            .setMessage(R.string.notif_help_message)
            .setPositiveButton(R.string.notif_help_open_settings) { _, _ ->
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.fromParts("package", packageName, null)
                })
            }
            .setNegativeButton(R.string.notif_help_close, null)
            .show()
    }

    // ── Misc helpers ──────────────────────────────────────────────────────────

    private fun getServerHost(serverUrl: String): String? =
        try { URL(serverUrl).host } catch (_: Exception) { null }
}
