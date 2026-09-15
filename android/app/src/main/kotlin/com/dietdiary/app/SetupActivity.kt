package com.dietdiary.app

import android.content.Intent
import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.dietdiary.app.databinding.ActivitySetupBinding
import javax.net.ssl.SSLHandshakeException

/**
 * First-launch screen: the user enters the server URL, optionally tests it,
 * then saves to [Prefs] and opens [MainActivity].
 *
 * Launched with intent extra {@code change_server = true} when the user wants
 * to update an already-saved URL.
 */
class SetupActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySetupBinding

    /** The normalised URL last successfully tested (or saved). */
    private var normalizedUrl: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Skip setup if a URL is already stored and we are not changing server
        if (!intent.getBooleanExtra("change_server", false)) {
            val saved = Prefs.getServerUrl(this)
            if (!saved.isNullOrBlank()) {
                goToMain()
                return
            }
        }

        binding = ActivitySetupBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // 预填：已保存的地址，否则使用内置默认服务器（可手动修改）
        binding.etServerUrl.setText(Prefs.getServerUrl(this) ?: BuildConfig.DEFAULT_SERVER_URL)
        // 默认地址允许直接保存（不强制先测试）
        binding.btnSave.isEnabled = true

        binding.btnTest.setOnClickListener { onTestClicked() }
        binding.btnSave.setOnClickListener { onSaveClicked() }
    }

    // ── Button handlers ───────────────────────────────────────────────────────

    private fun onTestClicked() {
        val input = binding.etServerUrl.text?.toString()?.trim().orEmpty()
        if (input.isBlank()) {
            showStatus(getString(R.string.setup_url_empty), success = false)
            return
        }
        normalizedUrl = normalizeUrl(input)
        testConnection(normalizedUrl)
    }

    private fun onSaveClicked() {
        val raw = binding.etServerUrl.text?.toString()?.trim().orEmpty()
        if (raw.isBlank()) {
            showStatus(getString(R.string.setup_url_empty), success = false)
            return
        }
        if (normalizedUrl.isBlank()) normalizedUrl = normalizeUrl(raw)
        Prefs.setServerUrl(this, normalizedUrl)
        // Reset registration flag so the new server gets a fresh device registration
        Prefs.setRegisterSent(this, false)
        goToMain()
    }

    // ── Connection test ───────────────────────────────────────────────────────

    private fun testConnection(urlStr: String) {
        showProgress(true)
        showStatus(getString(R.string.setup_testing), success = null)
        binding.btnSave.isEnabled = false

        Thread {
            try {
                val resp = Http.get(applicationContext, "$urlStr/api/health")
                runOnUiThread {
                    showProgress(false)
                    if (resp.code == 200 && resp.body.contains("ok")) {
                        showStatus(getString(R.string.setup_success), success = true)
                        binding.btnSave.isEnabled = true
                    } else {
                        showStatus(getString(R.string.setup_fail), success = false)
                    }
                }
            } catch (e: SSLHandshakeException) {
                runOnUiThread {
                    showProgress(false)
                    showSslDialog(urlStr)
                }
            } catch (_: Exception) {
                runOnUiThread {
                    showProgress(false)
                    showStatus(getString(R.string.setup_fail), success = false)
                }
            }
        }.start()
    }

    private fun showSslDialog(urlStr: String) {
        val host = try { java.net.URL(urlStr).host } catch (_: Exception) { urlStr }
        AlertDialog.Builder(this)
            .setTitle(R.string.ssl_dialog_title)
            .setMessage(R.string.ssl_dialog_message)
            .setPositiveButton(R.string.ssl_continue) { _, _ ->
                Prefs.trustHost(this, host)
                testConnection(urlStr)   // retry with trust-all
            }
            .setNegativeButton(R.string.ssl_cancel) { _, _ ->
                showStatus(getString(R.string.setup_fail), success = false)
            }
            .show()
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private fun normalizeUrl(input: String): String {
        var url = input.trim()
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            url = "https://$url"
        }
        return url.trimEnd('/')
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun showProgress(show: Boolean) {
        binding.progressBar.visibility = if (show) View.VISIBLE else View.GONE
    }

    private fun showStatus(msg: String, success: Boolean?) {
        binding.tvStatus.visibility = View.VISIBLE
        binding.tvStatus.text = msg
        binding.tvStatus.setTextColor(
            when (success) {
                true -> ContextCompat.getColor(this, android.R.color.holo_green_dark)
                false -> ContextCompat.getColor(this, android.R.color.holo_red_dark)
                null -> ContextCompat.getColor(this, android.R.color.darker_gray)
            }
        )
    }
}
