package com.dietdiary.app

import android.content.Context
import android.content.SharedPreferences
import java.util.UUID

/**
 * Centralised SharedPreferences wrapper.
 * All persistent app state lives here.
 */
object Prefs {

    private const val NAME = "diet_diary_prefs"

    private const val KEY_SERVER_URL = "server_url"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_LAST_INBOX_ID = "last_inbox_id"
    private const val KEY_NOTIF_ASKED = "notif_permission_asked"
    private const val KEY_REGISTER_SENT = "register_device_sent"
    private const val KEY_AUTH_TOKEN = "auth_token"

    private fun sp(ctx: Context): SharedPreferences =
        ctx.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    // ── Server URL ────────────────────────────────────────────────────────────

    fun getServerUrl(ctx: Context): String? = sp(ctx).getString(KEY_SERVER_URL, null)

    fun setServerUrl(ctx: Context, url: String) {
        sp(ctx).edit().putString(KEY_SERVER_URL, url.trimEnd('/')).apply()
    }

    fun clearServerUrl(ctx: Context) {
        sp(ctx).edit().remove(KEY_SERVER_URL).apply()
    }

    // ── Device ID (random UUID, generated once and persisted) ─────────────────

    fun getDeviceId(ctx: Context): String {
        val sp = sp(ctx)
        var id = sp.getString(KEY_DEVICE_ID, null)
        if (id.isNullOrBlank()) {
            id = UUID.randomUUID().toString()
            sp.edit().putString(KEY_DEVICE_ID, id).apply()
        }
        return id
    }

    // ── Inbox poll state ──────────────────────────────────────────────────────

    fun getLastInboxId(ctx: Context): Long = sp(ctx).getLong(KEY_LAST_INBOX_ID, 0L)

    fun setLastInboxId(ctx: Context, id: Long) {
        sp(ctx).edit().putLong(KEY_LAST_INBOX_ID, id).apply()
    }

    // ── Notification permission ───────────────────────────────────────────────

    fun wasNotifPermissionAsked(ctx: Context): Boolean =
        sp(ctx).getBoolean(KEY_NOTIF_ASKED, false)

    fun setNotifPermissionAsked(ctx: Context) {
        sp(ctx).edit().putBoolean(KEY_NOTIF_ASKED, true).apply()
    }

    // ── Register device (sent flag, reset on server URL change) ──────────────

    fun wasRegisterSent(ctx: Context): Boolean =
        sp(ctx).getBoolean(KEY_REGISTER_SENT, false)

    fun setRegisterSent(ctx: Context, sent: Boolean) {
        sp(ctx).edit().putBoolean(KEY_REGISTER_SENT, sent).apply()
    }

    // ── Auth token (fallback for InboxWorker when WebView cookies are gone) ──

    fun getAuthToken(ctx: Context): String? = sp(ctx).getString(KEY_AUTH_TOKEN, null)

    fun setAuthToken(ctx: Context, token: String?) {
        if (token == null) sp(ctx).edit().remove(KEY_AUTH_TOKEN).apply()
        else sp(ctx).edit().putString(KEY_AUTH_TOKEN, token).apply()
    }

    // ── 原生拍照上传结果（页面重载后可恢复） ───────────────────────────────────

    private const val KEY_PENDING_UPLOAD = "pending_upload"

    fun getPendingUpload(ctx: Context): String = sp(ctx).getString(KEY_PENDING_UPLOAD, "") ?: ""

    fun setPendingUpload(ctx: Context, json: String?) {
        if (json.isNullOrBlank()) sp(ctx).edit().remove(KEY_PENDING_UPLOAD).apply()
        else sp(ctx).edit().putString(KEY_PENDING_UPLOAD, json).apply()
    }

    // ── 电池优化提示只弹一次 ───────────────────────────────────────────────────

    private const val KEY_BATTERY_ASKED = "battery_asked"

    fun wasBatteryAsked(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_BATTERY_ASKED, false)

    fun setBatteryAsked(ctx: Context) {
        sp(ctx).edit().putBoolean(KEY_BATTERY_ASKED, true).apply()
    }

    // ── 实时通知前台服务（默认开启） ───────────────────────────────────────────

    private const val KEY_REALTIME = "realtime_notifications"

    fun isRealtimeEnabled(ctx: Context): Boolean = sp(ctx).getBoolean(KEY_REALTIME, true)

    fun setRealtimeEnabled(ctx: Context, enabled: Boolean) {
        sp(ctx).edit().putBoolean(KEY_REALTIME, enabled).apply()
    }

    // ── Trusted hosts (self-signed / user-accepted certs) ─────────────────────

    private const val KEY_TRUSTED_HOSTS = "trusted_hosts"

    fun isHostTrusted(ctx: Context, host: String): Boolean =
        sp(ctx).getStringSet(KEY_TRUSTED_HOSTS, emptySet())?.contains(host) == true

    fun trustHost(ctx: Context, host: String) {
        val current = sp(ctx).getStringSet(KEY_TRUSTED_HOSTS, emptySet())?.toMutableSet() ?: mutableSetOf()
        current.add(host)
        sp(ctx).edit().putStringSet(KEY_TRUSTED_HOSTS, current).apply()
    }

    // ── Full clear (called from "清除缓存与登录") ──────────────────────────────

    fun clearAll(ctx: Context) {
        // Keep server URL so the user doesn't have to re-enter it
        val url = getServerUrl(ctx)
        val deviceId = getDeviceId(ctx) // keep stable device ID too
        sp(ctx).edit().clear().apply()
        if (url != null) setServerUrl(ctx, url)
        sp(ctx).edit().putString(KEY_DEVICE_ID, deviceId).apply()
    }
}
