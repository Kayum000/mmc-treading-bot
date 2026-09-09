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
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import androidx.core.content.FileProvider;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
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

    private WebView webView;
    private DownloadManager downloadManager;
    private final Handler handler = new Handler(Looper.getMainLooper());
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
        webView.setWebChromeClient(new WebChromeClient());
        webView.loadUrl(APP_URL);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    this::handleBack
            );
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        checkForLatestUpdate();
        handler.removeCallbacks(updatePoll);
        handler.postDelayed(updatePoll, 10000L);
    }

    @Override
    protected void onPause() {
        super.onPause();
        handler.removeCallbacks(updatePoll);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "MMC Signal Alerts", NotificationManager.IMPORTANCE_HIGH);
        channel.setDescription("BUY and SELL signal alerts");
        channel.enableVibration(true);
        Uri soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
        AudioAttributes audioAttributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build();
        channel.setSound(soundUri, audioAttributes);
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.createNotificationChannel(channel);
    }

    private void createUpdateNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(UPDATE_CHANNEL_ID, "MMC App Updates", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("MMC Live Signal app update notifications");
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.createNotificationChannel(channel);
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
        }
    }

    private void checkForLatestUpdate() {
        if (updateCheckRunning) return;
        updateCheckRunning = true;
        new Thread(() -> {
            try {
                HttpURLConnection connection = (HttpURLConnection) new URL(RELEASE_API).openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(7000);
                connection.setReadTimeout(7000);
                connection.setRequestProperty("Accept", "application/vnd.github+json");
                if (connection.getResponseCode() != 200) return;
                InputStream stream = connection.getInputStream();
                BufferedReader reader = new BufferedReader(new InputStreamReader(stream));
                StringBuilder body = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) body.append(line);
                reader.close();
                Matcher nameMatcher = Pattern.compile("\\\"name\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"").matcher(body.toString());
                if (!nameMatcher.find()) return;
                Matcher versionMatcher = Pattern.compile("(?i)\\bv(\\d+)\\b").matcher(nameMatcher.group(1));
                if (!versionMatcher.find()) return;
                int latestVersion = Integer.parseInt(versionMatcher.group(1));
                if (latestVersion <= BuildConfig.VERSION_CODE) return;
                SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
                long existingId = prefs.getLong(PREF_UPDATE_ID, -1L);
                int existingVersion = prefs.getInt(PREF_UPDATE_VERSION, -1);
                if (existingVersion == latestVersion && existingId > 0) return;
                runOnUiThread(() -> startUpdateDownload(latestVersion));
            } catch (Exception ignored) {
            } finally {
                updateCheckRunning = false;
            }
        }).start();
    }

    private void startUpdateDownload(int version) {
        if (downloadManager == null) return;
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        long existingId = prefs.getLong(PREF_UPDATE_ID, -1L);
        int existingVersion = prefs.getInt(PREF_UPDATE_VERSION, -1);
        if (existingId > 0 && existingVersion == version) return;

        File apk = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "MMC-Live-Signal-update.apk");
        if (apk.exists()) apk.delete();
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(UPDATE_URL));
        request.setTitle("MMC Live Signal update");
        request.setDescription("Downloading the latest app version");
        request.setMimeType("application/vnd.android.package-archive");
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setDestinationInExternalFilesDir(this, Environment.DIRECTORY_DOWNLOADS, "MMC-Live-Signal-update.apk");
        long id = downloadManager.enqueue(request);
        prefs.edit().putLong(PREF_UPDATE_ID, id).putInt(PREF_UPDATE_VERSION, version).apply();
        Toast.makeText(this, "নতুন অ্যাপ ভার্সন ডাউনলোড হচ্ছে…", Toast.LENGTH_LONG).show();
    }

    private void checkPendingUpdate() {
        if (downloadManager == null) return;
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        long id = prefs.getLong(PREF_UPDATE_ID, -1L);
        if (id <= 0) return;
        DownloadManager.Query query = new DownloadManager.Query().setFilterById(id);
        android.database.Cursor cursor = downloadManager.query(query);
        if (cursor == null) return;
        try {
            if (!cursor.moveToFirst()) return;
            int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
            if (status == DownloadManager.STATUS_SUCCESSFUL) {
                prefs.edit().remove(PREF_UPDATE_ID).remove(PREF_UPDATE_VERSION).apply();
                installDownloadedUpdate();
            } else if (status == DownloadManager.STATUS_FAILED) {
                prefs.edit().remove(PREF_UPDATE_ID).remove(PREF_UPDATE_VERSION).apply();
            }
        } finally {
            cursor.close();
        }
    }

    private void installDownloadedUpdate() {
        File apk = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "MMC-Live-Signal-update.apk");
        if (!apk.exists()) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getPackageManager().canRequestPackageInstalls()) {
            Intent settings = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getPackageName()));
            startActivity(settings);
            Toast.makeText(this, "Update install করতে এই অ্যাপের অনুমতি দিন, তারপর অ্যাপটি আবার খুলুন।", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            Uri uri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", apk);
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        } catch (Exception ignored) {
        }
    }

    private void handleBack() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else finish();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) handleBack();
        else super.onBackPressed();
    }

    public static class SignalAlertBridge {
        private final Context context;
        private final SharedPreferences prefs;

        SignalAlertBridge(Context context) {
            this.context = context.getApplicationContext();
            this.prefs = this.context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        }

        @JavascriptInterface
        public String getDeviceId() {
            String id = prefs.getString(PREF_DEVICE_ID, null);
            if (id == null || id.trim().isEmpty()) {
                id = UUID.randomUUID().toString();
                prefs.edit().putString(PREF_DEVICE_ID, id).apply();
            }
            return id;
        }

        @JavascriptInterface
        public void notifySignal(String signal, String pair) {
            String upper = signal == null ? "" : signal.toUpperCase();
            if (!upper.equals("BUY") && !upper.equals("SELL")) return;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
            NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) return;
            Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
            PendingIntent pendingIntent = null;
            if (launch != null) {
                pendingIntent = PendingIntent.getActivity(context, 10, launch,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            }
            Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                    ? new Notification.Builder(context, CHANNEL_ID)
                    : new Notification.Builder(context);
            builder.setSmallIcon(R.drawable.ic_sk_bot)
                    .setContentTitle("MMC " + upper + " SIGNAL")
                    .setContentText((pair == null ? "Market" : pair) + " — " + upper)
                    .setPriority(Notification.PRIORITY_HIGH)
                    .setAutoCancel(true)
                    .setDefaults(Notification.DEFAULT_ALL);
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
                builder.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION));
            }
            if (pendingIntent != null) builder.setContentIntent(pendingIntent);
            manager.notify((int) (System.currentTimeMillis() & 0x7fffffff), builder.build());
        }
    }
}
