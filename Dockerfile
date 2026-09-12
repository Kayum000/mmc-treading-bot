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
    -e 's/"Twelve Data"/"BiQuote"/g' \
    -e "s/'Twelve Data'/'BiQuote'/g" {} +

# Permanently remove the obsolete crypto/Quotex UI from the deployed template.
RUN python - <<'PY'
from pathlib import Path
import re

path = Path("web/templates/index.html")
text = path.read_text(encoding="utf-8")

# Remove the MARKET MODE / QUOTEX OTC selector entirely.
text = re.sub(r'\s*<div class="mode-tabs">.*?</div>', '', text, count=1, flags=re.S)
text = re.sub(r'\s*<div style="width:100%"><strong>MARKET MODE</strong></div>', '', text, count=1)

# Keep one fixed Real Forex mode value; there is no crypto mode anymore.
text = re.sub(r'<input type="hidden" name="mode" id="mode" value="\{\{mode\}\}">', '<input type="hidden" name="mode" id="mode" value="real">', text, count=1)

# Remove the crypto market option loop from the market selector.
text = re.sub(r'\{% for p in crypto_pairs %\}.*?\{% endfor %\}', '', text, count=1, flags=re.S)

# Remove obsolete crypto-specific browser state and OTC display mapping.
text = re.sub(r'const OTC_LABELS=.*?;\n', '', text, count=1, flags=re.S)
text = re.sub(r'const displayPair=.*?;\n', '', text, count=1, flags=re.S)
text = text.replace(",STORAGE_CRYPTO='mmc_selected_crypto_pair'", '')
text = re.sub(r"function savedPairForMode\(mode\)\{.*?\}", "function savedPairForMode(){return localStorage.getItem(STORAGE_REAL)||''}", text, count=1, flags=re.S)
text = re.sub(r"function saveCurrentPair\(\)\{.*?\}", "function saveCurrentPair(){const pair=pairSelect.value;if(pair)localStorage.setItem(STORAGE_REAL,pair)}", text, count=1, flags=re.S)
text = re.sub(r"function setMode\(.*?\}\n", '', text, count=1, flags=re.S)
text = text.replace("displayPair(r.pair)", "r.pair")
text = text.replace("displayPair(d.pair)", "d.pair")
text = re.sub(r"document\.querySelectorAll\('\.mode-btn'\)\.forEach\(b=>b\.addEventListener\('click'.*?\}\)\);", '', text, count=1, flags=re.S)
text = re.sub(r"const serverMode=.*?scheduleAutoSignal\(\);scheduleNews\(\);scheduleStatus\(\);", "const serverPair={{ pair|tojson }};modeInput.value='real';if(serverPair&&pairSelect.value!==serverPair){const option=Array.from(pairSelect.options).find(o=>o.dataset.market==='real'&&o.value===serverPair);if(option)pairSelect.value=serverPair;updateSignalButton()}scheduleAutoSignal();scheduleNews();scheduleStatus();", text, count=1, flags=re.S)

path.write_text(text, encoding="utf-8")
PY

# No browser, Chromium, Playwright, Xvfb, Quotex, or crypto UI is shipped/started.
CMD ["python", "main.py"]
