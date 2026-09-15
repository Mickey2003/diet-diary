package com.dietdiary.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Manages the notification channel and posts individual/group notifications.
 */
object Notifier {

    const val CHANNEL_ID = "diet_diary_inbox"
    const val GROUP_KEY = "diet_diary"

    /** Create the notification channel (safe to call multiple times). */
    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val name = context.getString(R.string.notif_channel_name)
            val desc = context.getString(R.string.notif_channel_desc)
            // HIGH：在通知栏弹出横幅提示，而不是只在状态栏放个图标
            val channel = NotificationChannel(CHANNEL_ID, name, NotificationManager.IMPORTANCE_HIGH)
                .apply { description = desc; enableVibration(true) }
            (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(channel)
        }
    }

    /** Post a single notification. [id] must be unique per message. */
    fun post(context: Context, id: Int, title: String, body: String, openUrl: String? = null) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            openUrl?.let { putExtra("open_url", it) }
        }
        val pi = PendingIntent.getActivity(
            context, id, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notif = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setGroup(GROUP_KEY)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setContentIntent(pi)
            .build()

        try {
            NotificationManagerCompat.from(context).notify(id, notif)
        } catch (_: SecurityException) {
            // POST_NOTIFICATIONS not granted — silently skip
        }
    }

    /** Post a group summary notification (needed when >3 individual ones are shown). */
    fun postGroupSummary(context: Context) {
        val summary = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setGroup(GROUP_KEY)
            .setGroupSummary(true)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(0, summary)
        } catch (_: SecurityException) {}
    }

    fun areEnabled(context: Context): Boolean =
        NotificationManagerCompat.from(context).areNotificationsEnabled()

    /** 桌面图标角标（依赖启动器支持；不支持时静默忽略）。 */
    fun applyBadge(context: Context, count: Int) {
        try {
            if (count > 0) me.leolin.shortcutbadger.ShortcutBadger.applyCount(context, count)
            else me.leolin.shortcutbadger.ShortcutBadger.removeCount(context)
        } catch (_: Exception) {}
    }
}
