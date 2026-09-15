package com.dietdiary.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.dietdiary.app.databinding.ActivityScanBinding
import com.google.zxing.BarcodeFormat
import com.google.zxing.ResultPoint
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.DefaultDecoderFactory

/**
 * 全屏条形码扫描（竖屏）。
 *
 * 通过 [setResult] 返回：
 *  - "code"   识别到的字符串
 *  - "format" 条码格式名（如 "EAN_13"）
 *
 * 用户取消或未授予相机权限时返回 RESULT_CANCELED。
 */
class ScanActivity : AppCompatActivity() {

    private lateinit var binding: ActivityScanBinding
    private var torchOn = false
    private var cameraGranted = false

    private val cameraPermLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted: Boolean ->
            if (granted) {
                cameraGranted = true
                binding.barcodeScannerView.resume()
            } else {
                Toast.makeText(this, R.string.scan_camera_denied, Toast.LENGTH_SHORT).show()
                setResult(RESULT_CANCELED)
                finish()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityScanBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val formats = listOf(
            BarcodeFormat.EAN_13,
            BarcodeFormat.EAN_8,
            BarcodeFormat.UPC_A,
            BarcodeFormat.UPC_E,
            BarcodeFormat.CODE_128,
            BarcodeFormat.QR_CODE
        )

        binding.barcodeScannerView.barcodeView.decoderFactory = DefaultDecoderFactory(formats)
        binding.barcodeScannerView.setStatusText(getString(R.string.scan_barcode_prompt))

        binding.barcodeScannerView.decodeSingle(object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult) {
                setResult(RESULT_OK, Intent().apply {
                    putExtra("code", result.text)
                    putExtra("format", result.barcodeFormat.toString())
                })
                finish()
            }

            override fun possibleResultPoints(resultPoints: MutableList<ResultPoint>) = Unit
        })

        binding.btnTorch.setOnClickListener {
            torchOn = !torchOn
            if (torchOn) binding.barcodeScannerView.setTorchOn()
            else binding.barcodeScannerView.setTorchOff()
        }

        // 相机权限：未授予则先申请，授予后再启动预览
        cameraGranted = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED
        if (!cameraGranted) {
            cameraPermLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onResume() {
        super.onResume()
        if (cameraGranted) binding.barcodeScannerView.resume()
    }

    override fun onPause() {
        super.onPause()
        binding.barcodeScannerView.pause()
    }
}
