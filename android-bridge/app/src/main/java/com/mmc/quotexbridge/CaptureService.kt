package com.mmc.quotexbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageFormat
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.IBinder
import android.util.Base64
import android.util.Log
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

class CaptureService : Service() {
    companion object {
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "data"
        const val EXTRA_ENDPOINT = "endpoint"
        const val EXTRA_SECRET = "secret"
        private const val CHANNEL = "mmc_capture"
        private const val TAG = "MMCBridge"
        private const val FRAME_INTERVAL_MS = 1000L
        private const val MAX_JPEG_BYTES = 220_000
    }

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null
    private var endpoint: String = ""
    private var secret: String = ""
    private val executor = Executors.newSingleThreadExecutor()
    private val lastFrameAt = AtomicLong(0L)

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        createNotificationChannel()
        startForeground(1001, notification())

        endpoint = (intent?.getStringExtra(EXTRA_ENDPOINT) ?: "").trim().trimEnd('/')
        secret = intent?.getStringExtra(EXTRA_SECRET) ?: ""

        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, -1) ?: -1
        val data = intent?.parcelableIntentExtra(EXTRA_DATA)
        if (resultCode < 0 || data == null || endpoint.isBlank() || secret.isBlank()) {
            Log.e(TAG, "Capture start rejected: missing permission, endpoint, or secret")
            stopSelf()
            return START_NOT_STICKY
        }

        val manager = getSystemService(MediaProjectionManager::class.java)
        projection = manager.getMediaProjection(resultCode, data)

        val metrics = resources.displayMetrics
        val width = metrics.widthPixels
        val height = metrics.heightPixels
        val density = metrics.densityDpi

        reader = ImageReader.newInstance(width, height, ImageFormat.RGBA_8888, 2)
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
            val now = System.currentTimeMillis()
            if (now - lastFrameAt.get() < FRAME_INTERVAL_MS) {
                source.acquireLatestImage()?.close()
                return@setOnImageAvailableListener
            }
            val image = source.acquireLatestImage() ?: return@setOnImageAvailableListener
            lastFrameAt.set(now)
            executor.execute {
                try {
                    encodeAndSend(image)
                } catch (t: Throwable) {
                    Log.w(TAG, "Frame processing failed: ${t.javaClass.simpleName}: ${t.message}")
                } finally {
                    image.close()
                }
            }
        }, null)

        Log.i(TAG, "Capture active: ${width}x${height}")
        return START_NOT_STICKY
    }

    private fun encodeAndSend(image: android.media.Image) {
        val plane = image.planes.firstOrNull() ?: return
        val buffer: ByteBuffer = plane.buffer
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        if (pixelStride <= 0 || rowStride <= 0) return

        val paddedWidth = rowStride / pixelStride
        val height = image.height
        if (paddedWidth < image.width || height <= 0) return

        val bitmap = Bitmap.createBitmap(paddedWidth, height, Bitmap.Config.ARGB_8888)
        buffer.rewind()
        bitmap.copyPixelsFromBuffer(buffer)
        val cropped = Bitmap.createBitmap(bitmap, 0, 0, image.width, image.height)
        bitmap.recycle()

        val targetWidth = minOf(720, cropped.width)
        val targetHeight = (cropped.height.toDouble() * targetWidth / cropped.width).toInt().coerceAtLeast(1)
        val scaled = Bitmap.createScaledBitmap(cropped, targetWidth, targetHeight, true)
        cropped.recycle()

        val output = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 55, output)
        scaled.recycle()
        var bytes = output.toByteArray()

        // Keep uploads bounded on mobile data. Lower quality only if necessary.
        if (bytes.size > MAX_JPEG_BYTES) {
            val retry = ByteArrayOutputStream()
            val bitmapRetry = Bitmap.createScaledBitmap(
                BitmapFactoryCompat.decodeJpeg(bytes),
                minOf(540, targetWidth),
                (targetHeight.toDouble() * minOf(540, targetWidth) / targetWidth).toInt().coerceAtLeast(1),
                true
            )
            bitmapRetry.compress(Bitmap.CompressFormat.JPEG, 45, retry)
            bitmapRetry.recycle()
            bytes = retry.toByteArray()
        }

        postFrame(bytes, image.width, image.height)
    }

    private fun postFrame(bytes: ByteArray, width: Int, height: Int) {
        val url = URL("$endpoint/quotex/android-frame")
        val connection = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 7000
            readTimeout = 7000
            doOutput = true
            setRequestProperty("Content-Type", "image/jpeg")
            setRequestProperty("X-MMC-Quotex-Key", secret)
            setRequestProperty("X-MMC-Frame-Time", (System.currentTimeMillis() / 1000.0).toString())
            setRequestProperty("X-MMC-Frame-Width", width.toString())
            setRequestProperty("X-MMC-Frame-Height", height.toString())
            setFixedLengthStreamingMode(bytes.size)
        }
        connection.outputStream.use { it.write(bytes) }
        val code = connection.responseCode
        val response = if (code in 200..299) connection.inputStream.bufferedReader().use { it.readText() } else ""
        connection.disconnect()
        if (code in 200..299) Log.d(TAG, "Frame sent: $width x $height -> $response")
        else Log.w(TAG, "Frame upload HTTP $code")
    }

    override fun onDestroy() {
        reader?.close()
        display?.release()
        projection?.stop()
        executor.shutdownNow()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun notification(): Notification =
        Notification.Builder(this, CHANNEL)
            .setContentTitle("MMC Quotex Bridge")
            .setContentText("Quotex screen scan active")
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

private object BitmapFactoryCompat {
    fun decodeJpeg(bytes: ByteArray): Bitmap {
        return android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: throw IllegalStateException("Unable to decode JPEG")
    }
}

private fun Intent.parcelableIntentExtra(key: String): Intent? =
    if (android.os.Build.VERSION.SDK_INT >= 33) {
        getParcelableExtra(key, Intent::class.java)
    } else {
        @Suppress("DEPRECATION")
        getParcelableExtra(key)
    }
