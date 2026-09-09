package com.kayum.mmc_trading_bot;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioAttributes;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;

public class MainActivity extends Activity {
    private static final String APP_URL = "https://mmc-treading-bot.onrender.com/";
    private static final String CHANNEL_ID = "mmc_signal_alerts";
    private WebView webView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        createNotificationChannel();
        requestNotificationPermission();

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

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "MMC Signal Alerts",
                NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription("BUY and SELL signal alerts");
        channel.enableVibration(true);
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.createNotificationChannel(channel);
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1001);
        }
    }

    private void handleBack() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            finish();
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            handleBack();
        } else {
            super.onBackPressed();
        }
    }

    public static class SignalAlertBridge {
        private final Context context;

        SignalAlertBridge(Context context) {
            this.context = context.getApplicationContext();
        }

        @JavascriptInterface
        public void notifySignal(String signal, String pair) {
            String upper = signal == null ? "" : signal.toUpperCase();
            if (!upper.equals("BUY") && !upper.equals("SELL")) return;

            NotificationManager manager = (NotificationManager)
                    context.getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null) return;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                    ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
                            != PackageManager.PERMISSION_GRANTED) return;

            Intent intent = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
            PendingIntent pendingIntent = null;
            if (intent != null) {
                pendingIntent = PendingIntent.getActivity(
                        context, 10, intent,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
                );
            }

            NotificationCompat.Builder builder = new NotificationCompat.Builder(context, CHANNEL_ID)
                    .setSmallIcon(com.kayum.mmc_trading_bot.R.drawable.ic_sk_bot_logo)
                    .setContentTitle("MMC " + upper + " SIGNAL")
                    .setContentText((pair == null ? "Market" : pair) + " — " + upper)
                    .setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setAutoCancel(true)
                    .setDefaults(NotificationCompat.DEFAULT_ALL);
            if (pendingIntent != null) builder.setContentIntent(pendingIntent);
            manager.notify((int) System.currentTimeMillis(), builder.build());
        }
    }
}
