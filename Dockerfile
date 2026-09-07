FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Finalize the Forex provider migration inside the deployed image.
# Legacy imports are rewritten to the BiQuote adapter before the app starts.
RUN find . -type f -name '*.py' -exec sed -i \
    -e 's/data\.twelve_data_forex/data.biquote_forex/g' \
    -e 's/\"Twelve Data\"/\"BiQuote\"/g' \
    -e "s/'Twelve Data'/'BiQuote'/g" {} +

# Load the compact equal-height dashboard panel CSS without changing the main template.
RUN grep -q 'panel_equalizer.css' web/templates/index.html || sed -i 's#</head>#<link rel="stylesheet" href="/static/panel_equalizer.css">\n</head>#' web/templates/index.html

# Load broker-style chart tools without altering the existing dashboard template.
RUN grep -q 'chart_tools.js' web/templates/index.html || sed -i 's#</body>#<script src="/static/chart_tools.js" defer></script>\n</body>#' web/templates/index.html

# Load the true tick-stream chart after the broker tools.
RUN grep -q 'live_stream_chart.js' web/templates/index.html || sed -i 's#</body>#<script src="/static/live_stream_chart.js" defer></script>\n</body>#' web/templates/index.html

CMD ["python", "main.py"]
