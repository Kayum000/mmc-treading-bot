# Android Quotex Bridge

This folder documents the optional Android-side source for the existing MMC signal engine.

## What this bridge does

- Quotex remains the app the user opens manually.
- The Android companion can capture the Quotex app screen after explicit Android screen-capture consent.
- When the companion can reliably extract **closed 1-minute OHLC/tick data**, it sends that structured data to:
  `POST /quotex/android-ingest`
- The server normalizes that data through the same existing OTC cache used by the current collector.
- The existing adaptive strategy remains unchanged.

## Important safety boundary

This is an additional data source, not a replacement for the current Windows/browser collector.

The bridge must **not** send a running candle as a closed candle. The server-side adapter already rejects candles whose full 60-second period has not elapsed.

The bridge also does not place trades or handle a Quotex password/session token.

## Android screen capture

Android's MediaProjection API requires explicit user consent for screen capture. On Android 14+ each capture session requires fresh user consent, and a media-projection foreground service must declare the appropriate foreground-service type/permission.

Because the exact Quotex Android chart layout and device resolution have not yet been validated, this repository intentionally does not guess pixel coordinates or claim that arbitrary screenshots are already convertible to trustworthy OHLC. That extraction step must be tested against the user's actual Quotex Android screen before it is connected to live signal generation.

## Payload shape

The bridge should POST JSON with the existing ingest secret:

```json
{
  "sent_at": 1760000000.0,
  "active_asset": "USDINR_otc",
  "candles": [
    {
      "asset": "USDINR_otc",
      "timestamp": 1760000000,
      "open": 1.0,
      "high": 1.1,
      "low": 0.9,
      "close": 1.05
    }
  ],
  "ticks": [
    {
      "asset": "USDINR_otc",
      "timestamp": 1760000000.5,
      "price": 1.05
    }
  ]
}
```

Use the same `X-MMC-Quotex-Key` header as the current authenticated collector.

## Current implementation status

The server endpoint is implemented and isolated. The next step is device-specific Android capture/extraction testing. Until that test succeeds, the existing Windows/browser collector remains the live fallback.
