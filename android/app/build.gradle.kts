import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Load keystore properties from env vars (CI) or local keystore.properties file
// 变量名加 env 前缀，避免与 signingConfig 的 keyAlias / keyPassword 属性同名冲突
val envKeystoreFile = System.getenv("KEYSTORE_FILE")
val envKeystorePassword = System.getenv("KEYSTORE_PASSWORD")
val envKeyAlias = System.getenv("KEY_ALIAS")
val envKeyPassword = System.getenv("KEY_PASSWORD")

val hasSigningConfig = !envKeystoreFile.isNullOrBlank() &&
        !envKeystorePassword.isNullOrBlank() &&
        !envKeyAlias.isNullOrBlank() &&
        !envKeyPassword.isNullOrBlank()

android {
    namespace = "com.dietdiary.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.dietdiary.app"
        minSdk = 21
        targetSdk = 34
        versionCode = 5
        versionName = "1.3.1"
        buildConfigField("String", "DEFAULT_SERVER_URL", "\"https://diet-diary.720172.xyz\"")
    }

    signingConfigs {
        if (hasSigningConfig) {
            create("release") {
                storeFile = file(envKeystoreFile!!)
                storePassword = envKeystorePassword
                keyAlias = envKeyAlias
                keyPassword = envKeyPassword
            }
        }
        // If no signing config is supplied, release falls back to debug signing
        // so CI always produces an installable APK.
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            signingConfig = if (hasSigningConfig) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildFeatures {
        buildConfig = true
        viewBinding = true
    }

    // Keep WebView state across rotation
    // (handled in manifest with configChanges, no extra build setting needed)

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    // AndroidX core
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")

    // WebKit (modern WebView APIs)
    implementation("androidx.webkit:webkit:1.11.0")

    // WorkManager
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // ZXing barcode scanning (no Google Play Services needed)
    // minSdk 21：按 zxing-android-embedded 文档，API < 24 需搭配 zxing core 3.3.0
    implementation("com.journeyapps:zxing-android-embedded:4.3.0") { isTransitive = false }
    implementation("com.google.zxing:core:3.3.0")

    // Activity Result API / OnBackPressedCallback（显式声明，避免依赖传递版本）
    implementation("androidx.activity:activity-ktx:1.9.2")
    // 桌面图标角标（MIUI / EMUI / ColorOS / 三星 / Nova 等启动器）
    implementation("me.leolin:ShortcutBadger:1.1.22@aar")
}
