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

# Keep the Forex provider migration deterministic without rewriting application code.
RUN find . -type f -name '*.py' -exec sed -i \
    -e 's/data\.twelve_data_forex/data.biquote_forex/g' \
    -e 's/"Twelve Data"/"BiQuote"/g' \
    -e "s/'Twelve Data'/'BiQuote'/g" {} +

# Quotex OTC uses a lightweight WebSocket client; no Chromium or Playwright is installed.
CMD ["python", "main.py"]
