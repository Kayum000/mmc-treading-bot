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

# Load the compact equal-height dashboard panel CSS without changing the main template.
RUN grep -q 'panel_equalizer.css' web/templates/index.html || sed -i 's#</head>#<link rel="stylesheet" href="/static/panel_equalizer.css">\n</head>#' web/templates/index.html

CMD ["python", "main.py"]
