package com.dietdiary.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** 开机后恢复轮询与实时通知服务。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (Prefs.getServerUrl(context).isNullOrBlank()) return
        InboxWorker.schedule(context)
        if (Prefs.isRealtimeEnabled(context)) InboxService.start(context)
    }
}
