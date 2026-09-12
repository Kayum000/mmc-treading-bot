# Quotex Android → MMC collector

This is the fallback path when the Quotex Android app works but the web terminal cannot be opened.

## Architecture

`Quotex Android app → USB/ADB screenshots → laptop candle detector → /quotex/ingest → Render MMC strategy`

Only detected candle data is sent to Render. The collector does not request or store a Quotex password, OTP, SSID/session token, balance, or order controls, and it never clicks Up/Down.

## Windows setup

1. Install Android SDK Platform Tools (`adb`) and Python 3.11+.
2. On the Android phone enable **Developer options → USB debugging**.
3. Connect the phone to the laptop with USB and accept the RSA debugging prompt on the phone.
4. Open the Quotex Android app and select the OTC market you want to analyze. Keep the **1-minute candlestick chart** visible.
5. From the repository root run:

```bat
tools\run_quotex_android_collector.bat
```

6. When asked for the Render secret, copy `QUOTEX_INGEST_SECRET` from the Render Environment page. Never put the secret in GitHub or chat.
7. The launcher defaults to `USDARS_otc`, matching the `USD/ARS (OTC)` pair shown in the tested phone recording. For another supported pair, enter its Quotex asset code when prompted.

## Detection behavior

The collector samples the Android display twice per second, detects the red/green candle bodies and wicks in the chart region, excludes the newest visible candle because it is normally still forming, and sends direction-preserving OHLC-like rows. The existing conservative OTC pressure strategy then produces BUY/SELL/HOLD.

Because this is screen-derived rather than a native Quotex market-data feed, the collector deliberately refuses to send data when too few candles are visible. It should be treated as a signal-data experiment, not a guarantee of price accuracy or profitability.

## Optional screen mirror

For convenience, the official `scrcpy` project can mirror the phone over USB/TCP, but the MMC collector itself uses `adb screencap` and does not require scrcpy.

## Troubleshooting

- `No authorized Android device`: enable USB debugging, reconnect USB, and accept the phone authorization prompt.
- `detected=0`: keep the Quotex 1-minute candlestick chart fully visible; close menus/overlays and wait for a candle to render.
- `accepted=0`: verify the asset code and Render `QUOTEX_INGEST_SECRET`.
- If the chart layout changes substantially, run with `QUOTEX_DEBUG_VERBOSE=1`; the detector can then be adjusted without changing the Render service.
