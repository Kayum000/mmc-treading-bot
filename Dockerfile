FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMIUM_BIN=/usr/bin/chromium

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
        chromium \
        chromium-driver \
    && ln -sf /usr/bin/chromium /usr/bin/google-chrome \
    && ln -sf /usr/bin/chromium /usr/bin/google-chrome-stable \
    && ln -sf /usr/bin/chromium /usr/local/bin/google-chrome \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Finalize the Forex provider migration inside the deployed image.
RUN find . -type f -name '*.py' -exec sed -i \
    -e 's/data\.twelve_data_forex/data.biquote_forex/g' \
    -e 's/\"Twelve Data\"/\"BiQuote\"/g' \
    -e "s/'Twelve Data'/'BiQuote'/g" {} +

# Load dashboard CSS and the single clean live-chart mount/engine.
RUN grep -q 'panel_equalizer.css' web/templates/index.html || sed -i 's#</head>#<link rel="stylesheet" href="/static/panel_equalizer.css">\n</head>#' web/templates/index.html
RUN sed -i '/chart_tools\.js/d' web/templates/index.html
RUN grep -q 'chart_mount.js' web/templates/index.html || sed -i 's#</body>#<script src="/static/chart_mount.js" defer></script>\n</body>#' web/templates/index.html
RUN grep -q 'live_stream_chart.js' web/templates/index.html || sed -i 's#</body>#<script src="/static/live_stream_chart.js" defer></script>\n</body>#' web/templates/index.html

CMD ["python", "main.py"]
