# MMC Telegram signal setup

Telegram notifications are optional and are disabled until both secrets are configured.

## 1. Set the bot token on Render

In the Render dashboard, open the `mmc-treading-bot` web service and go to **Environment**. Add:

- `TELEGRAM_BOT_TOKEN` — the token from BotFather
- `TELEGRAM_CHAT_ID` — your private chat ID or a Telegram group ID
- `TELEGRAM_SIGNALS_ENABLED` — `true`

Never commit the real token to GitHub or send it in chat.

## 2. Find your chat ID

1. Open your bot in Telegram and press **Start** or send `/start`.
2. Add `TELEGRAM_BOT_TOKEN` in Render first and wait for the service to deploy.
3. Sign in to the MMC dashboard in the same browser.
4. Open `/api/telegram-chats` on that same dashboard origin. It returns recent chat IDs received by the bot.
5. Set the desired `chat_id` as `TELEGRAM_CHAT_ID` in Render and redeploy.

If no chats appear, send `/start` again and refresh the endpoint. For a group, add the bot to that group and send a message there.

## 3. Test

While signed in to the dashboard, open `/api/telegram-status` to verify configuration, then open `/api/telegram-test` to send a test message.

## Behavior

A Telegram message is sent when MMC generates a new BUY or SELL signal through the manual GET SIGNAL or dashboard AUTO signal endpoint. HOLD results are ignored, and repeated requests for the same signal are deduplicated within the running process. The dashboard's AUTO signal loop must be active for ongoing automatic alerts; this integration does not execute trades.

The alert contains pair, market mode, entry reference price when available, Bangladesh entry time, confidence, strategy/regime, and the signal reason. Stop-loss and take-profit are not invented because the current signal payload does not calculate them.
