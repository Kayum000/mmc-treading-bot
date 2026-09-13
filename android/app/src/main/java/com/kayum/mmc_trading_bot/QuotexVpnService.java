package com.kayum.mmc_trading_bot;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.net.VpnService;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;

/**
 * Same-device Quotex connector foundation.
 *
 * This service deliberately does NOT install a default route yet. A VpnService
 * without a forwarding backend would black-hole the phone's traffic. The next
 * connector layer must provide packet forwarding before traffic interception
 * is enabled.
 */
public class QuotexVpnService extends VpnService {
    public static final String ACTION_START = "com.kayum.mmc_trading_bot.action.VPN_START";
    public static final String ACTION_STOP = "com.kayum.mmc_trading_bot.action.VPN_STOP";
    private static final String CHANNEL_ID = "mmc_quotex_connector";
    private static final int NOTIFICATION_ID = 4701;

    private ParcelFileDescriptor vpnInterface;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
        Notification notification = new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_sk_bot)
                .setContentTitle("MMC Quotex Connector")
                .setContentText("Connector service is ready")
                .setOngoing(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification,
                    android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopVpn();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (vpnInterface == null) establishDiagnosticInterface();
        return START_STICKY;
    }

    private void establishDiagnosticInterface() {
        try {
            // No 0.0.0.0/0 route is installed until a real packet-forwarding
            // backend is present. This keeps the current MMC/Quotex networking intact.
            vpnInterface = new Builder()
                    .setSession("MMC Quotex Connector")
                    .setMtu(1500)
                    .addAddress("10.7.0.2", 32)
                    .establish();
        } catch (Exception ignored) {
            vpnInterface = null;
        }
    }

    private void stopVpn() {
        if (vpnInterface != null) {
            try { vpnInterface.close(); } catch (Exception ignored) { }
            vpnInterface = null;
        }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "MMC Quotex Connector",
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Same-device Quotex connector service");
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.createNotificationChannel(channel);
    }

    @Override
    public void onDestroy() {
        stopVpn();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return super.onBind(intent);
    }
}
