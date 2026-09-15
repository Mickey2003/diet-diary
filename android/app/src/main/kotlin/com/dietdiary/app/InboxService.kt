package com.dietdiary.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.webkit.CookieManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * 实时通知前台服务：对服务器收件箱做长轮询（GET /api/notify/inbox?wait=25），
 * 一有新消息立刻弹系统通知。WorkManager 的 15 分钟轮询作为兜底继续保留。
 *
 * 前台服务需要一条常驻的低优先级通知（“正在监听通知”），这是 Android 的要求；
 * 用户可在系统设置里把该渠道静音，不影响正常通知。
 */
class InboxService : Service() {

    @Volatile
    private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureForegroundChannel()
        val notification = buildForegroundNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(FG_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(FG_ID, notification)
        }
        if (!running) {
            running = true
            worker = Thread({ loop() }, "inbox-longpoll").also { it.isDaemon = true; it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun loop() {
        var backoffMs = 3_000L
        while (running) {
            try {
                val ctx = applicationContext
                val server = Prefs.getServerUrl(ctx)
                val cookie = CookieManager.getInstance().getCookie(server ?: "")
                if (server.isNullOrBlank() || cookie.isNullOrBlank()) {
                    Thread.sleep(15_000); continue
                }
                val sinceId = Prefs.getLastInboxId(ctx)
                val resp = Http.get(ctx, "$server/api/notify/inbox?since_id=$sinceId&unread_only=true&wait=25",
                    mapOf("Cookie" to cookie), timeoutMs = 40_000)
                when (resp.code) {
                    200 -> {
                        backoffMs = 3_000L
                        val root = JSONObject(resp.body)
                        val arr = root.optJSONArray("messages") ?: JSONArray()
                        Notifier.applyBadge(ctx, root.optInt("unread", 0))
                        var maxId = sinceId
                        val ids = JSONArray()
                        for (i in 0 until arr.length()) {
                            val m = arr.getJSONObject(i)
                            val id = m.getLong("id")
                            if (id > maxId) maxId = id
                            ids.put(id)
                            val urlPath: String? = if (m.isNull("url")) null else m.optString("url")
                            Notifier.post(ctx, id.toInt(), m.getString("title"), m.getString("body"),
                                if (!urlPath.isNullOrBlank()) "$server$urlPath" else null)
                            val extra = m.optJSONObject("extra")
                            val soundUrl = extra?.optString("sound_url", "") ?: ""
                            if (m.optString("kind") == "meal_alert" && soundUrl.isNotBlank()) {
                                SoundPlayer.playFromServer(ctx, soundUrl,
                                    extra!!.optDouble("volume", 0.8).toFloat(), extra.optBoolean("vibrate", true))
                            }
                        }
                        if (arr.length() > 3) Notifier.postGroupSummary(ctx)
                        if (maxId > sinceId) Prefs.setLastInboxId(ctx, maxId)
                        if (ids.length() > 0) Http.post(ctx, "$server/api/notify/inbox/read", ids.toString(), mapOf("Cookie" to cookie))
                    }
                    401 -> Thread.sleep(60_000)   // 未登录：稍后再试
                    else -> { Thread.sleep(backoffMs); backoffMs = (backoffMs * 2).coerceAtMost(120_000L) }
                }
            } catch (_: InterruptedException) {
                return
            } catch (_: Exception) {
                try { Thread.sleep(backoffMs) } catch (_: InterruptedException) { return }
                backoffMs = (backoffMs * 2).coerceAtMost(120_000L)
            }
        }
    }

    private fun ensureForegroundChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(FG_CHANNEL, getString(R.string.fg_channel_name), NotificationManager.IMPORTANCE_MIN)
                .apply { description = getString(R.string.fg_channel_desc); setShowBadge(false) }
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).createNotificationChannel(ch)
        }
    }

    private fun buildForegroundNotification(): Notification {
        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, FG_CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.fg_notification_title))
            .setContentText(getString(R.string.fg_notification_text))
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(pi)
            .build()
    }

    companion object {
        private const val FG_ID = 1001
        const val FG_CHANNEL = "diet_diary_service"

        fun start(context: Context) {
            val intent = Intent(context, InboxService::class.java)
            try {
                ContextCompat.startForegroundService(context, intent)
            } catch (_: Exception) {
                // Android 12+ 后台启动前台服务受限时忽略；下次进入 App 会再启动
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, InboxService::class.java))
        }
    }
}
