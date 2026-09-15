package com.dietdiary.app

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.webkit.CookieManager

/**
 * 播放服务器上的提醒音效（预设或用户上传）。用于就餐提醒等带 sound_url 的收件箱消息。
 * 使用 MediaPlayer 流式播放，带登录 Cookie；播放完成自动释放。
 */
object SoundPlayer {

    @Volatile
    private var current: MediaPlayer? = null

    fun playFromServer(context: Context, soundUrl: String, volume: Float = 0.8f, vibrate: Boolean = true) {
        val server = Prefs.getServerUrl(context) ?: return
        val url = if (soundUrl.startsWith("http")) soundUrl else server.trimEnd('/') + soundUrl
        val cookie = CookieManager.getInstance().getCookie(server) ?: ""
        try {
            current?.release()
            val mp = MediaPlayer()
            mp.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            val headers = mutableMapOf("User-Agent" to Http.USER_AGENT)
            if (cookie.isNotBlank()) headers["Cookie"] = cookie
            mp.setDataSource(context, Uri.parse(url), headers)
            val v = volume.coerceIn(0f, 1f)
            mp.setVolume(v, v)
            mp.setOnPreparedListener { it.start() }
            mp.setOnCompletionListener { it.release(); if (current === it) current = null }
            mp.setOnErrorListener { p, _, _ -> p.release(); if (current === p) current = null; true }
            current = mp
            mp.prepareAsync()
        } catch (_: Exception) {
        }
        if (vibrate) vibrateShort(context)
    }

    private fun vibrateShort(context: Context) {
        try {
            val vib: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            if (vib == null || !vib.hasVibrator()) return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 200, 120, 200), -1))
            } else {
                @Suppress("DEPRECATION")
                vib.vibrate(400)
            }
        } catch (_: Exception) {
        }
    }
}
