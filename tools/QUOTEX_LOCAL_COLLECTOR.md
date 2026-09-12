# Quotex live-browser collector

This setup lets MMC read the **same live WebSocket traffic that the user's own Quotex web terminal receives**. It does not use screenshots/OCR, does not ask for a Quotex password or SSID, and does not place orders.

## One-time Render setting

`QUOTEX_INGEST_SECRET` has already been added to the Render service. Do not put that value in GitHub. Copy it from Render's Environment page only when starting the local collector.

## Windows setup

1. Make sure the repo is present on the Windows PC and Python 3.11+ is installed.
2. Open `tools\start_quotex_debug_chrome.bat`.
3. A separate Chrome profile opens with DevTools on `127.0.0.1:9222`.
4. Log in to Quotex in that new Chrome profile and open the OTC chart.
5. Leave the Quotex tab open.
6. Run `tools\run_quotex_collector.bat`.
7. Paste the `QUOTEX_INGEST_SECRET` copied from Render when prompted.

Chrome requires a non-default user-data directory when remote debugging is enabled on current versions, so the helper deliberately uses `%LocalAppData%\MMC-Quotex-Chrome` instead of your normal Chrome profile.

## What is sent to Render

Only supported OTC candle/price data is forwarded:

- asset
- 1-minute timestamp
- open
- high
- low
- close

The collector never forwards browser cookies, passwords, SSID/session tokens, account balance, or order messages.

## Signal path

`Quotex Web Terminal -> Chrome DevTools Network WebSocket events -> local 1-minute OHLC collector -> /quotex/ingest -> MMC OTC strategy -> BUY/SELL/HOLD`

The Render service prefers fresh browser-collector data. If it is not available and `QUOTEX_SSID`/`QUOTEX_SESSION_TOKEN` is configured, the existing direct WebSocket fallback remains available.

## Important

This is an unofficial integration because Quotex does not publish a public developer API. The browser stream/protocol can change. Keep development/testing on the demo account and do not enable automatic order execution.
