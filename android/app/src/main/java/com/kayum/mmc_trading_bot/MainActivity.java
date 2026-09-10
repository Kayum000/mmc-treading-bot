package com.kayum.mmc_trading_bot;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {
    private static final String APP_URL = "https://mmc-treading-bot.onrender.com/";
    private static final String CHANNEL_ID = "mmc_signal_alerts_v2";
    private static final String UPDATE_CHANNEL_ID = "mmc_app_updates";
    private static final String UPDATE_URL = "https://github.com/Kayum000/mmc-treading-bot/releases/latest/download/app-debug.apk";
    private static final String RELEASE_API = "https://api.github.com/repos/Kayum000/mmc-treading-bot/releases/latest";
    private static final String PREFS = "mmc_app";
    private static final String PREF_DEVICE_ID = "stable_device_id";
    private static final String PREF_UPDATE_ID = "download_id";
    private static final String PREF_UPDATE_VERSION = "download_version";
    private static final int FILE_CHOOSER_REQUEST_CODE = 2101;

    private WebView webView;
    private DownloadManager downloadManager;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private ValueCallback<Uri[]> pendingFileCallback;
    private Uri pendingCameraUri;
    private boolean updateCheckRunning;
    private final Runnable updatePoll = new Runnable() {
        @Override public void run() {
            checkPendingUpdate();
            handler.postDelayed(this, 10000L);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createNotificationChannel();
        createUpdateNotificationChannel();
        requestNotificationPermission();

        downloadManager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        webView = new WebView(this);
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        webView.addJavascriptInterface(new SignalAlertBridge(this), "AndroidSignalAlert");
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> filePathCallback,
                                              FileChooserParams fileChooserParams) {
                if (pendingFileCallback != null) pendingFileCallback.onReceiveValue(null);
                pendingFileCallback = filePathCallback;
                pendingCameraUri = null;
                if (fileChooserParams.isCaptureEnabled()) openCameraOnly();
                else openChartImageChooser(fileChooserParams);
                return true;
            }
        });
        webView.loadUrl(APP_URL);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    this::handleBack
            );
        }
    }

    private void openCameraOnly() {
        Intent cameraIntent = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        if (cameraIntent.resolveActivity(getPackageManager()) == null) {
            finishFileChooser(null);
            Toast.makeText(this, "এই ডিভাইসে Camera পাওয়া যাচ্ছে না।", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            File cameraFile = File.createTempFile("mmc_chart_", ".jpg", getExternalCacheDir());
            pendingCameraUri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", cameraFile);
            cameraIntent.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, pendingCameraUri);
            cameraIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            cameraIntent.setClipData(android.content.ClipData.newRawUri("chart", pendingCameraUri));
            startActivityForResult(cameraIntent, FILE_CHOOSER_REQUEST_CODE);
        } catch (Exception exc) {
            pendingCameraUri = null;
            finishFileChooser(null);
            Toast.makeText(this, "Camera খোলা যাচ্ছে না।", Toast.LENGTH_LONG).show();
        }
    }

    private void openChartImageChooser(WebChromeClient.FileChooserParams params) {
        Intent galleryIntent;
        try { galleryIntent = params.createIntent(); }
        catch (Exception ignored) {
            galleryIntent = new Intent(Intent.ACTION_GET_CONTENT);
            galleryIntent.addCategory(Intent.CATEGORY_OPENABLE);
            galleryIntent.setType("image/*");
        }
        galleryIntent.addCategory(Intent.CATEGORY_OPENABLE);
        galleryIntent.setType("image/*");
        Intent cameraIntent = new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);
        if (cameraIntent.resolveActivity(getPackageManager()) == null) { launchGalleryOnly(galleryIntent); return; }
        try {
            File cameraFile = File.createTempFile("mmc_chart_", ".jpg", getExternalCacheDir());
            pendingCameraUri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", cameraFile);
            cameraIntent.putExtra(android.provider.MediaStore.EXTRA_OUTPUT, pendingCameraUri);
            cameraIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            cameraIntent.setClipData(android.content.ClipData.newRawUri("chart", pendingCameraUri));
            Intent chooser = Intent.createChooser(galleryIntent, "Select chart image or Camera");
            chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cameraIntent});
            startActivityForResult(chooser, FILE_CHOOSER_REQUEST_CODE);
        } catch (Exception ignored) { pendingCameraUri = null; launchGalleryOnly(galleryIntent); }
    }

    private void launchGalleryOnly(Intent galleryIntent) {
        try { startActivityForResult(galleryIntent, FILE_CHOOSER_REQUEST_CODE); }
        catch (Exception exc) { finishFileChooser(null); Toast.makeText(this, "ছবি নির্বাচন করার অপশন খোলা যাচ্ছে না।", Toast.LENGTH_LONG).show(); }
    }

    private void finishFileChooser(Uri uri) {
        if (pendingFileCallback != null) {
            pendingFileCallback.onReceiveValue(uri == null ? null : new Uri[]{uri});
            pendingFileCallback = null;
        }
        pendingCameraUri = null;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER_REQUEST_CODE) return;
        Uri result = null;
        if (resultCode == RESULT_OK) {
            if (data != null && data.getData() != null) result = data.getData();
            else if (pendingCameraUri != null) result = pendingCameraUri;
        }
        finishFileChooser(result);
    }

    @Override protected void onDestroy() {
        if (pendingFileCallback != null) { pendingFileCallback.onReceiveValue(null); pendingFileCallback = null; }
        super.onDestroy();
    }

    @Override protected void onResume() {
        super.onResume(); checkForLatestUpdate(); handler.removeCallbacks(updatePoll); handler.postDelayed(updatePoll, 10000L);
    }
    @Override protected void onPause() { super.onPause(); handler.removeCallbacks(updatePoll); }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "MMC Signal Alerts", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("BUY and SELL signal alerts"); channel.enableVibration(true);
        Uri soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
        AudioAttributes audioAttributes = new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
        channel.setSound(soundUri, audioAttributes);
        NotificationManager manager = getSystemService(NotificationManager.class); if (manager != null) manager.createNotificationChannel(channel);
    }
    private void createUpdateNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(UPDATE_CHANNEL_ID, "MMC App Updates", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("MMC Live Signal app update notifications");
        NotificationManager manager = getSystemService(NotificationManager.class); if (manager != null) manager.createNotificationChannel(channel);
    }
    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
    }

    private void checkForLatestUpdate() {
        if (updateCheckRunning) return; updateCheckRunning = true;
        new Thread(() -> {
            try {
                HttpURLConnection connection = (HttpURLConnection) new URL(RELEASE_API).openConnection();
                connection.setRequestMethod("GET"); connection.setConnectTimeout(7000); connection.setReadTimeout(7000); connection.setRequestProperty("Accept", "application/vnd.github+json");
                if (connection.getResponseCode() != 200) return;
                BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream())); StringBuilder body = new StringBuilder(); String line;
                while ((line = reader.readLine()) != null) body.append(line); reader.close();
                Matcher publishedMatcher = Pattern.compile("\\\"published_at\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"").matcher(body.toString()); if (!publishedMatcher.find()) return;
                SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US); format.setTimeZone(TimeZone.getTimeZone("UTC")); Date published = format.parse(publishedMatcher.group(1)); if (published == null) return;
                long buildTime = BuildConfig.BUILD_TIMESTAMP_MS; if (published.getTime() <= buildTime + (10 * 60 * 1000L)) return;
                SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE); long existingId = prefs.getLong(PREF_UPDATE_ID, -1L); long releaseTime = published.getTime(); long existingVersion = prefs.getLong(PREF_UPDATE_VERSION, -1L);
                if (existingVersion == releaseTime && existingId > 0) return; runOnUiThread(() -> startUpdateDownload(releaseTime));
            } catch (Exception ignored) { } finally { updateCheckRunning = false; }
        }).start();
    }
    private void startUpdateDownload(long releaseTime) {
        if (downloadManager == null) return; SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE); long existingId = prefs.getLong(PREF_UPDATE_ID, -1L); long existingVersion = prefs.getLong(PREF_UPDATE_VERSION, -1L); if (existingId > 0 && existingVersion == releaseTime) return;
        File apk = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "MMC-Live-Signal-update.apk"); if (apk.exists()) apk.delete(); DownloadManager.Request request = new DownloadManager.Request(Uri.parse(UPDATE_URL)); request.setTitle("MMC Live Signal update"); request.setDescription("Downloading the latest app version"); request.setMimeType("application/vnd.android.package-archive"); request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED); request.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, "MMC-Live-Signal-update.apk"); long id = downloadManager.enqueue(request); prefs.edit().putLong(PREF_UPDATE_ID, id).putLong(PREF_UPDATE_VERSION, releaseTime).apply(); Toast.makeText(this, "নতুন অ্যাপ ভার্সন ডাউনলোড হচ্ছে…", Toast.LENGTH_LONG).show();
    }
    private void checkPendingUpdate() {
        if (downloadManager == null) return; SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE); long id = prefs.getLong(PREF_UPDATE_ID, -1L); if (id <= 0) return; DownloadManager.Query query = new DownloadManager.Query().setFilterById(id); android.database.Cursor cursor = downloadManager.query(query); if (cursor == null) return;
        try { if (!cursor.moveToFirst()) return; int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)); if (status == DownloadManager.STATUS_SUCCESSFUL) { prefs.edit().remove(PREF_UPDATE_ID).remove(PREF_UPDATE_VERSION).apply(); installDownloadedUpdate(); } else if (status == DownloadManager.STATUS_FAILED) prefs.edit().remove(PREF_UPDATE_ID).remove(PREF_UPDATE_VERSION).apply(); } finally { cursor.close(); }
    }
    private void installDownloadedUpdate() {
        File apk = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "MMC-Live-Signal-update.apk"); if (!apk.exists()) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getPackageManager().canRequestPackageInstalls()) { Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName())); startActivity(settings); Toast.makeText(this, "Update install করতে এই অ্যাপের অনুমতি দিন, তারপর অ্যাপটি আবার খুলুন।", Toast.LENGTH_LONG).show(); return; }
        try { Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", apk); Intent intent = new Intent(Intent.ACTION_VIEW); intent.setDataAndType(uri, "application/vnd.android.package-archive"); intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK); startActivity(intent); } catch (Exception ignored) { }
    }
    private void handleBack() { if (webView != null && webView.canGoBack()) webView.goBack(); else finish(); }
    @Override @SuppressWarnings("deprecation") public void onBackPressed() { if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) handleBack(); else super.onBackPressed(); }

    public static class SignalAlertBridge {
        private final Context context; private final SharedPreferences prefs;
        SignalAlertBridge(Context context) { this.context = context.getApplicationContext(); this.prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE); }
        @JavascriptInterface public String getDeviceId() { String id = prefs.getString(PREF_DEVICE_ID, null); if (id == null || id.trim().isEmpty()) { id = UUID.randomUUID().toString(); prefs.edit().putString(PREF_DEVICE_ID, id).apply(); } return id; }
        @JavascriptInterface public void setDeviceId(String id) { if (id == null) return; id = id.trim(); if (!id.isEmpty() && id.length() <= 200) prefs.edit().putString(PREF_DEVICE_ID, id).apply(); }
        @JavascriptInterface public void notifySignal(String signal, String pair) {
            String upper = signal == null ? "" : signal.toUpperCase(); if (!upper.equals("BUY") && !upper.equals("SELL")) return;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE); if (manager == null) return;
            Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName()); PendingIntent pendingIntent = null; if (launch != null) pendingIntent = PendingIntent.getActivity(context, 10, launch, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O ? new Notification.Builder(context, CHANNEL_ID) : new Notification.Builder(context);
            builder.setSmallIcon(R.drawable.ic_sk_bot).setContentTitle("MMC " + upper + " SIGNAL").setContentText((pair == null ? "Market" : pair) + " — " + upper).setPriority(Notification.PRIORITY_HIGH).setAutoCancel(true).setDefaults(Notification.DEFAULT_ALL);
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)); if (pendingIntent != null) builder.setContentIntent(pendingIntent); manager.notify((int) (System.currentTimeMillis() & 0x7fffffff), builder.build());
        }
    }
}
