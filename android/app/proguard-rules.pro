# Add project specific ProGuard rules here.

# ---- ZXing ----
-keep class com.google.zxing.** { *; }
-keep class com.journeyapps.barcodescanner.** { *; }

# ---- WebView JavaScript interface ----
# Keep all classes that are injected into WebView via addJavascriptInterface.
# The bridge class must NOT be renamed because its methods are called by name from JS.
-keepclassmembers class com.dietdiary.app.WebAppInterface {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.dietdiary.app.WebAppInterface { *; }

# ---- AndroidX WorkManager ----
-keep class androidx.work.** { *; }
-keep class * extends androidx.work.Worker
-keep class * extends androidx.work.ListenableWorker {
    public <init>(android.content.Context, androidx.work.WorkerParameters);
}

# ---- Kotlin coroutines ----
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}

# ---- General Android keep rules ----
-keepattributes *Annotation*
-keepattributes SourceFile,LineNumberTable
-keep public class * extends android.app.Activity
-keep public class * extends android.app.Service
-keep public class * extends android.content.BroadcastReceiver
-keep public class * extends android.content.ContentProvider
-keep public class * extends android.view.View
