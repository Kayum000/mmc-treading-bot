import os
import webbrowser

APP_URL = os.getenv("MMC_APP_URL", "https://mmc-treading-bot.onrender.com/")

if __name__ == "__main__":
    webbrowser.open(APP_URL, new=2)
