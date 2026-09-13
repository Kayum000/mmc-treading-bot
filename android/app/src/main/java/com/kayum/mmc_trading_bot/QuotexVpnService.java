package com.kayum.mmc_trading_bot;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.VpnService;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

import hev.htproxy.TProxyService;

/** Same-device Quotex per-app VPN with a local direct SOCKS5 forwarding layer. */
public class QuotexVpnService extends VpnService {
    public static final String ACTION_START = "com.kayum.mmc_trading_bot.action.VPN_START";
    public static final String ACTION_STOP = "com.kayum.mmc_trading_bot.action.VPN_STOP";
    private static final String CHANNEL_ID = "mmc_quotex_connector";
    private static final int NOTIFICATION_ID = 4701;
    private static final String QUOTEX_PACKAGE = "io.quotex.x";

    private ParcelFileDescriptor vpnInterface;
    private DirectSocks5Server socks;
    private boolean tunnelRunning;

    @Override public void onCreate() {
        super.onCreate();
        createChannel();
        Notification n = new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_sk_bot)
                .setContentTitle("MMC Quotex Connector")
                .setContentText("Quotex traffic connector running")
                .setOngoing(true).setCategory(Notification.CATEGORY_SERVICE).build();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            startForeground(NOTIFICATION_ID, n, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(NOTIFICATION_ID, n);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopVpn(); stopSelf(); return START_NOT_STICKY;
        }
        if (!tunnelRunning) startTunnel();
        return START_STICKY;
    }

    private void startTunnel() {
        try {
            getPackageManager().getPackageInfo(QUOTEX_PACKAGE, 0);
        } catch (PackageManager.NameNotFoundException e) {
            stopSelf(); return;
        }
        try {
            socks = new DirectSocks5Server(this);
            socks.start();

            VpnService.Builder b = new VpnService.Builder()
                    .setSession("MMC Quotex Connector")
                    .setMtu(1500)
                    .addAddress("10.7.0.2", 32)
                    .addAddress("fc00::1", 128)
                    .addRoute("0.0.0.0", 0)
                    .addRoute("::", 0)
                    .addAllowedApplication(QUOTEX_PACKAGE);

            vpnInterface = b.establish();
            if (vpnInterface == null) throw new IllegalStateException("VPN establish failed");

            File cfg = new File(getCacheDir(), "quotex-tunnel.yml");
            String yaml = "tunnel:\n" +
                    "  name: tun0\n" +
                    "  mtu: 1500\n" +
                    "  ipv4: '10.7.0.2'\n" +
                    "  ipv6: 'fc00::1'\n" +
                    "socks5:\n" +
                    "  address: 127.0.0.1\n" +
                    "  port: 1080\n" +
                    "  udp: 'tcp'\n" +
                    "misc:\n" +
                    "  log-level: warn\n";
            try (FileOutputStream out = new FileOutputStream(cfg)) {
                out.write(yaml.getBytes(StandardCharsets.UTF_8));
            }

            tunnelRunning = TProxyService.TProxyStartService(cfg.getAbsolutePath(), vpnInterface.getFd());
            if (!tunnelRunning) throw new IllegalStateException("tun2socks start failed");
        } catch (Exception e) {
            stopVpn();
            stopSelf();
        }
    }

    private void stopVpn() {
        if (tunnelRunning) {
            try { TProxyService.TProxyStopService(); } catch (Throwable ignored) {}
            tunnelRunning = false;
        }
        if (vpnInterface != null) { try { vpnInterface.close(); } catch (Exception ignored) {} vpnInterface = null; }
        if (socks != null) { socks.stop(); socks = null; }
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel c = new NotificationChannel(CHANNEL_ID, "MMC Quotex Connector", NotificationManager.IMPORTANCE_LOW);
        c.setDescription("Same-device Quotex connector service");
        NotificationManager m = getSystemService(NotificationManager.class);
        if (m != null) m.createNotificationChannel(c);
    }

    @Override public void onDestroy() { stopVpn(); super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return super.onBind(intent); }
}
