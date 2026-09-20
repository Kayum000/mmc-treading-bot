package com.mmc.quotexbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.IBinder
import android.util.Log

class CaptureService : Service() {
    companion object {
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        const val EXTRA_ENDPOINT = "endpoint"
        const val EXTRA_SECRET = "secret"
        private const val CHANNEL = "mmc_capture"
        private const val TAG = "MMCBridge"
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        createNotificationChannel()
        startForeground(1001, notification())

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, -1) ?: -1
        val data = intent?.parcelableIntentExtra(EXTRA_DATA)
        if (resultCode < 0 || data == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        val manager = getSystemService(MediaProjectionManager::class.java)
        projection = manager.getMediaProjection(resultCode, data)

        val metrics = resources.displayMetrics
        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        display = projection?.createVirtualDisplay(
            "MMCQuotexBridge",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader?.surface,
            null,
            null
        )

        reader?.setOnImageAvailableListener({ source ->
            source.acquireLatestImage()?.use { image ->
                // Capture is intentionally wired but chart/OHLC extraction is not
                // guessed from arbitrary pixels. The next calibration step maps
                // the user's actual Quotex layout to reliable candle data.
                Log.d(TAG, "Quotex frame captured: undefinedxundefined")
            }
        }, null)

        return START_STICKY
    }

    override fun onDestroy() {
        reader?.close()
        display?.release()
        projection?.stop()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun notification(): Notification =
        Notification.Builder(this, CHANNEL)
            .setContentTitle("MMC Quotex Bridge")
            .setContentText("Quotex screen capture active")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setOngoing(true)
            .build()

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "MMC Quotex Bridge", NotificationManager.IMPORTANCE_LOW)
        )
    }
}

private fun Intent.parcelableIntentExtra(key: String): Intent? =
    if (android.os.Build.VERSION.SDK_INT >= 33) {
        getParcelableExtra(key, Intent::class.java)
    } else {
        @Suppress("DEPRECATION")
        getParcelableExtra(key)
    }
