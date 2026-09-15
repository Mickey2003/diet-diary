package com.dietdiary.app

import android.content.Context
import android.os.Build
import android.webkit.CookieManager
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * WorkManager [Worker] that polls the server inbox, posts notifications for
 * new messages, and marks them as read.
 */
class InboxWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {

    override fun doWork(): Result {
        val context = applicationContext
        val server = Prefs.getServerUrl(context) ?: return Result.success()

        val cookie = CookieManager.getInstance().getCookie(server)
        if (cookie.isNullOrBlank()) return Result.success()

        val sinceId = Prefs.getLastInboxId(context)

        return try {
            val resp = Http.get(
                context,
                "$server/api/notify/inbox?since_id=$sinceId&unread_only=true",
                mapOf("Cookie" to cookie)
            )

            when (resp.code) {
                200 -> {
                    // 服务端返回 {"messages":[...], "unread":n, "server_time":...}
                    val root = JSONObject(resp.body)
                    val array = root.optJSONArray("messages") ?: JSONArray()
                    Notifier.applyBadge(context, root.optInt("unread", 0))
                    val messages = mutableListOf<JSONObject>()
                    var maxId = sinceId

                    for (i in 0 until array.length()) {
                        val msg = array.getJSONObject(i)
                        messages.add(msg)
                        val id = msg.getLong("id")
                        if (id > maxId) maxId = id
                    }

                    // Post individual notifications
                    messages.forEach { msg ->
                        val id = msg.getLong("id").toInt()
                        val title = msg.getString("title")
                        val body = msg.getString("body")
                        val urlPath: String? = if (msg.isNull("url")) null else msg.optString("url")
                        val openUrl = if (!urlPath.isNullOrBlank()) "$server$urlPath" else null
                        Notifier.post(context, id, title, body, openUrl)
                        val extra = msg.optJSONObject("extra")
                        val soundUrl = extra?.optString("sound_url", "") ?: ""
                        if (msg.optString("kind") == "meal_alert" && soundUrl.isNotBlank()) {
                            SoundPlayer.playFromServer(context, soundUrl,
                                extra!!.optDouble("volume", 0.8).toFloat(), extra.optBoolean("vibrate", true))
                        }
                    }

                    // Group summary when many notifications are posted
                    if (messages.size > 3) {
                        Notifier.postGroupSummary(context)
                    }

                    // Persist the highest seen id
                    if (maxId > sinceId) Prefs.setLastInboxId(context, maxId)

                    // Mark messages as read
                    if (messages.isNotEmpty()) {
                        val ids = JSONArray().also { arr -> messages.forEach { arr.put(it.getLong("id")) } }
                        Http.post(
                            context,
                            "$server/api/notify/inbox/read",
                            ids.toString(),
                            mapOf("Cookie" to cookie)
                        )
                    }

                    Result.success()
                }
                401 -> Result.success()   // Logged out — nothing to do
                else -> Result.retry()
            }
        } catch (_: IOException) {
            Result.retry()
        }
    }

    companion object {
        private const val WORK_PERIODIC = "inbox-poll"
        private const val WORK_ONCE = "inbox-once"

        /** Enqueue a periodic poll every 15 minutes (when network is connected). */
        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = PeriodicWorkRequestBuilder<InboxWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_PERIODIC,
                ExistingPeriodicWorkPolicy.KEEP,
                request
            )
        }

        /** Run the inbox check once immediately (replaces any pending one-shot). */
        fun runOnce(context: Context) {
            val request = OneTimeWorkRequestBuilder<InboxWorker>().build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_ONCE,
                ExistingWorkPolicy.REPLACE,
                request
            )
        }

        /**
         * Register this device with the server's push notification endpoint.
         * Runs on a background thread; silently ignores failures.
         */
        fun registerDevice(context: Context) {
            Thread {
                try {
                    val server = Prefs.getServerUrl(context) ?: return@Thread
                    val cookie = CookieManager.getInstance().getCookie(server)
                    if (cookie.isNullOrBlank()) return@Thread

                    val body = JSONObject().apply {
                        put("device_id", Prefs.getDeviceId(context))
                        put("name", Build.MODEL)
                        put("platform", "android")
                        put("app_version", BuildConfig.VERSION_NAME)
                    }.toString()

                    Http.post(
                        context,
                        "$server/api/notify/devices",
                        body,
                        mapOf("Cookie" to cookie)
                    )
                    Prefs.setRegisterSent(context, true)
                } catch (_: Exception) {
                    // Silently fail — will retry next time MainActivity reloads
                }
            }.start()
        }
    }
}
