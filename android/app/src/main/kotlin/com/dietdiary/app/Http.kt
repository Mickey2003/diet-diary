package com.dietdiary.app

import android.content.Context
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.X509TrustManager

/**
 * 极简 HTTP 工具：GET / POST(JSON) / POST(multipart)；对用户明确信任的主机允许自签名证书。
 */
object Http {

    private const val TIMEOUT_MS = 10_000
    const val USER_AGENT = "DietDiaryApp/1.3 (Android)"

    private val trustAllFactory: SSLSocketFactory by lazy {
        val tm = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) = Unit
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        SSLContext.getInstance("TLS").also { it.init(null, arrayOf(tm), SecureRandom()) }.socketFactory
    }

    private val trustAllHostnameVerifier: HostnameVerifier = HostnameVerifier { _, _ -> true }

    data class Response(val code: Int, val body: String)

    fun get(
        context: Context,
        urlString: String,
        headers: Map<String, String> = emptyMap(),
        timeoutMs: Int = TIMEOUT_MS
    ): Response = request(context, urlString, null, "application/json", headers, timeoutMs)

    fun post(
        context: Context,
        urlString: String,
        body: String = "",
        headers: Map<String, String> = emptyMap()
    ): Response = request(context, urlString, body.toByteArray(Charsets.UTF_8), "application/json", headers, TIMEOUT_MS)

    /** multipart/form-data 上传单个文件字段。 */
    fun postMultipart(
        context: Context,
        urlString: String,
        fieldName: String,
        fileName: String,
        bytes: ByteArray,
        mime: String = "image/jpeg",
        headers: Map<String, String> = emptyMap()
    ): Response {
        val boundary = "----DietDiary${System.currentTimeMillis()}"
        val head = ("--$boundary\r\n" +
                "Content-Disposition: form-data; name=\"$fieldName\"; filename=\"$fileName\"\r\n" +
                "Content-Type: $mime\r\n\r\n").toByteArray(Charsets.UTF_8)
        val tail = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)
        val body = ByteArray(head.size + bytes.size + tail.size)
        System.arraycopy(head, 0, body, 0, head.size)
        System.arraycopy(bytes, 0, body, head.size, bytes.size)
        System.arraycopy(tail, 0, body, head.size + bytes.size, tail.size)
        return request(context, urlString, body, "multipart/form-data; boundary=$boundary", headers, 60_000)
    }

    private fun openConnection(context: Context, urlString: String): HttpURLConnection {
        val url = URL(urlString)
        val conn = url.openConnection() as HttpURLConnection
        if (conn is HttpsURLConnection && Prefs.isHostTrusted(context, url.host)) {
            conn.sslSocketFactory = trustAllFactory
            conn.hostnameVerifier = trustAllHostnameVerifier
        }
        return conn
    }

    private fun request(
        context: Context,
        urlString: String,
        body: ByteArray?,
        contentType: String,
        headers: Map<String, String>,
        timeoutMs: Int
    ): Response {
        val conn = openConnection(context, urlString)
        return try {
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = timeoutMs
            conn.setRequestProperty("User-Agent", USER_AGENT)
            headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", contentType)
                conn.setFixedLengthStreamingMode(body.size)
                conn.outputStream.use { it.write(body) }
            } else {
                conn.requestMethod = "GET"
            }
            val code = conn.responseCode
            val responseBody = try {
                conn.inputStream.bufferedReader(Charsets.UTF_8).readText()
            } catch (_: IOException) {
                conn.errorStream?.bufferedReader(Charsets.UTF_8)?.readText() ?: ""
            }
            Response(code, responseBody)
        } finally {
            conn.disconnect()
        }
    }
}
