# MMC Android APK build

The main Android app is built in GitHub Actions by `.github/workflows/build-main-apk.yml`.

Build command: `gradle --no-daemon assembleDebug` from this directory.

The workflow uploads `android/app/build/outputs/apk/debug/app-debug.apk` as the `mmc-main-app-debug-apk` artifact. This file documents the build output and intentionally does not contain credentials or runtime secrets.
