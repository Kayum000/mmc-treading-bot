import os
import webview

APP_URL = os.getenv("MMC_APP_URL", "https://mmc-treading-bot.onrender.com/")

if __name__ == "__main__":
    webview.create_window(
        "MMC Live Signal",
        APP_URL,
        width=1280,
        height=820,
        min_size=(900, 600),
        text_select=True,
    )
    webview.start(gui="edgechromium", debug=False)
