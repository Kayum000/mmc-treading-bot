package com.mmc.quotexbridge

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    companion object { private const val REQUEST_CAPTURE = 4001 }

    private lateinit var endpoint: EditText
    private lateinit var secret: EditText
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        status = TextView(this).apply {
            text = "MMC Android Bridge — প্রস্তুত"
            textSize = 18f
        }
        endpoint = EditText(this).apply {
            hint = "Render URL, যেমন https://mmc-treading-bot.onrender.com"
            setText("https://mmc-treading-bot.onrender.com")
        }
        secret = EditText(this).apply {
            hint = "QUOTEX_INGEST_SECRET"
        }
        val start = Button(this).apply {
            text = "Quotex Screen Scan শুরু করুন"
            setOnClickListener { requestCapture() }
        }
        val stop = Button(this).apply {
            text = "Scan বন্ধ করুন"
            setOnClickListener {
                stopService(Intent(this@MainActivity, CaptureService::class.java))
                status.text = "Scan বন্ধ"
            }
        }
        box.addView(status)
        box.addView(endpoint)
        box.addView(secret)
        box.addView(start)
        box.addView(stop)
        setContentView(box)
    }

    private fun requestCapture() {
        val manager = getSystemService(MediaProjectionManager::class.java)
        startActivityForResult(manager.createScreenCaptureIntent(), REQUEST_CAPTURE)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_CAPTURE || resultCode != Activity.RESULT_OK || data == null) {
            status.text = "Screen capture অনুমতি দেওয়া হয়নি"
            return
        }
        val service = Intent(this, CaptureService::class.java).apply {
            putExtra(CaptureService.EXTRA_RESULT_CODE, resultCode)
            putExtra(CaptureService.EXTRA_DATA, data)
            putExtra(CaptureService.EXTRA_ENDPOINT, endpoint.text.toString().trim())
            putExtra(CaptureService.EXTRA_SECRET, secret.text.toString())
        }
        startForegroundService(service)
        status.text = "Capture service চালু হয়েছে"
    }
}
