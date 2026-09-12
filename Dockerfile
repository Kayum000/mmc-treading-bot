FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
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

# Hide/remove the obsolete crypto mode from the legacy template at build time.
RUN grep -q 'forex_only.js' web/templates/index.html || sed -i 's#</body>#<script src="/static/forex_only.js" defer></script>\n</body>#' web/templates/index.html

# Keep the Render image lightweight: no Chromium, Playwright, Xvfb, or Quotex.
CMD ["python", "main.py"]
