package com.kayum.mmc_trading_bot;

import android.content.Intent;
import android.net.VpnService;
import android.os.ParcelFileDescriptor;

/**
 * Local VPN foundation for same-device Quotex traffic diagnostics.
 *
 * This intentionally does not claim to decrypt TLS/WSS traffic. It establishes
 * the Android VpnService permission/lifecycle and keeps the tunnel non-invasive
 * until a forwarding/inspection backend is added.
 */
public class QuotexVpnService extends VpnService {
    public static final String ACTION_START = "com.kayum.mmc_trading_bot.action.VPN_START";
    public static final String ACTION_STOP = "com.kayum.mmc_trading_bot.action.VPN_STOP";

    private ParcelFileDescriptor vpnInterface;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopVpn();
            stopSelf();
            return START_NOT_STICKY;
        }
        if (vpnInterface == null) {
            establishVpn();
        }
        return START_STICKY;
    }

    private void establishVpn() {
        try {
            Builder builder = new Builder()
                    .setSession("MMC Quotex Connector")
                    .setMtu(1500)
                    .addAddress("10.7.0.2", 32);
            vpnInterface = builder.establish();
        } catch (Exception ignored) {
            vpnInterface = null;
        }
    }

    private void stopVpn() {
        if (vpnInterface != null) {
            try {
                vpnInterface.close();
            } catch (Exception ignored) {
            }
            vpnInterface = null;
        }
    }

    @Override
    public void onDestroy() {
        stopVpn();
        super.onDestroy();
    }
}
