"""Optional chart screenshot/camera scanner for independent visual analysis.

This module does NOT modify the existing v2.1 tick strategy. It is an
independent dashboard tool: the user captures/uploads a chart image and the
vision model returns BUY/SELL/AVOID plus the exact server analysis time.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import jsonify, request

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MODEL = os.getenv("CHART_SCANNER_MODEL", "gpt-5.6-luna")


def _extract_output_text(payload: dict) -> str:
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if text:
                parts.append(text)
    if parts:
        return "\n".join(parts).strip()
    return str(payload.get("output_text", "")).strip()


def _analyze_image(data_url: str, analysis_time_bd: str, pair: str) -> dict:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "setup_required": True, "error": "Chart Scanner-এর জন্য OPENAI_API_KEY এখনো Render-এ সেট করা হয়নি।"}
    prompt = f"""
You are the independent chart-vision scanner inside an FX/crypto dashboard.
Analyze ONLY the supplied chart image. Do not invent prices or indicators that
are not visible. The existing bot strategy is separate and must not be changed.
Selected market: {pair or 'unknown'}
Analysis time (Bangladesh): {analysis_time_bd}
Inspect visible candles, trend/market structure, support/resistance, breakouts
or fakeouts, momentum, volatility, and any clearly visible indicators. If the
image is unclear, cropped, stale, or insufficient for a directional decision,
choose AVOID.
Return ONLY valid JSON with exactly these keys:
signal: one of BUY, SELL, AVOID
signal_time_bd: the supplied analysis time exactly
confidence: integer 0-100
trend: short description
reason: concise explanation based only on visible evidence
risk: LOW, MEDIUM, or HIGH
""".strip()
    body = {"model": MODEL, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": data_url, "detail": "high"}]}]}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode("utf-8"), headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        return {"ok": False, "error": f"Vision API error ({exc.code}): {detail}"}
    except Exception as exc:
        return {"ok": False, "error": f"Chart Scanner connection error: {exc}"}
    try:
        result = json.loads(_extract_output_text(payload))
    except Exception:
        return {"ok": False, "error": "Vision model-এর response JSON format-এ পাওয়া যায়নি।"}
    signal = str(result.get("signal", "AVOID")).upper()
    if signal not in {"BUY", "SELL", "AVOID"}:
        signal = "AVOID"
    try:
        confidence = max(0, min(100, int(result.get("confidence", 0))))
    except Exception:
        confidence = 0
    return {"ok": True, "signal": signal, "signal_time_bd": str(result.get("signal_time_bd") or analysis_time_bd), "confidence": confidence, "trend": str(result.get("trend", "—")), "reason": str(result.get("reason", "—")), "risk": str(result.get("risk", "HIGH")).upper(), "model": MODEL, "independent": True}


def init_chart_scanner_ui(app):
    @app.route("/chart-scanner", methods=["POST"])
    def chart_scanner():
        upload = request.files.get("chart")
        if upload is None or not upload.filename:
            return jsonify({"ok": False, "error": "একটি chart screenshot/camera image দিন।"}), 400
        raw = upload.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            return jsonify({"ok": False, "error": "Image size সর্বোচ্চ 8 MB হতে পারবে।"}), 413
        content_type = (upload.mimetype or "image/jpeg").lower()
        if content_type not in {"image/jpeg", "image/jpg", "image/png", "image/webp"}:
            return jsonify({"ok": False, "error": "শুধু JPG, PNG বা WebP chart image দিন।"}), 400
        mode = request.form.get("mode", "real").strip().lower()
        pair = request.form.get("pair", "").strip().upper()
        now_bd = datetime.now(ZoneInfo("Asia/Dhaka")).strftime("%Y-%m-%d %H:%M:%S BST")
        data_url = f"data:{content_type};base64,{base64.b64encode(raw).decode('ascii')}"
        result = _analyze_image(data_url, now_bd, pair)
        result["market_mode"] = mode
        return jsonify(result)

    @app.after_request
    def inject_chart_scanner(response):
        if not response.content_type or not response.content_type.startswith("text/html"):
            return response
        html = response.get_data(as_text=True)
        if 'id="chart-scanner-trigger"' in html:
            return response
        css = """
<style>
#chart-scanner-trigger{display:inline-flex;align-items:center;gap:6px;margin:0 0 10px 4px;padding:10px 13px;border:1px solid #8bb4ff;border-radius:9px;background:#fff;color:#174ea6;font-weight:900;cursor:pointer}
#chart-scanner-overlay{display:none;position:fixed;inset:0;z-index:6000;background:rgba(15,23,42,.48);align-items:center;justify-content:center;padding:16px}
#chart-scanner-overlay.open{display:flex}.chart-scanner-card{width:min(620px,100%);max-height:calc(100vh - 32px);overflow:auto;background:#fff;border-radius:16px;padding:18px;box-shadow:0 18px 60px rgba(0,0,0,.3)}
.chart-scanner-head{display:flex;justify-content:space-between;align-items:center}.chart-scanner-head h3{margin:0;font-size:22px}.chart-scanner-close{background:#172033!important;padding:7px 10px!important;color:#fff;border:0;border-radius:8px}
.chart-scanner-input{margin:14px 0;padding:14px;border:2px dashed #b8cffd;border-radius:12px;background:#f8fbff;text-align:center}
.chart-camera-row{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}.chart-source-btn{border:0;border-radius:10px;padding:12px 8px;font-weight:900;cursor:pointer;background:#2563eb;color:#fff}.chart-source-btn.gallery{background:#475569}
.chart-source-btn input{display:none}#chart-scanner-preview{display:none;max-width:100%;max-height:300px;margin:12px auto;border-radius:10px;border:1px solid #dbe4f0}.chart-scan-btn{width:100%;margin-top:8px;border:0;border-radius:10px;padding:12px;background:#0f766e;color:#fff;font-weight:900;cursor:pointer}.chart-scan-result{margin-top:14px;padding:14px;border-radius:12px;background:#f8fafc;border:1px solid #dbe4f0}.chart-scan-signal{font-size:30px;font-weight:900;text-align:center;color:#174ea6}.chart-scan-meta{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}.chart-scan-meta div{padding:9px;background:#fff;border:1px solid #e2e8f0;border-radius:8px}.chart-scanner-note{margin-top:10px;font-size:12px;color:#64748b;line-height:1.45}
</style>
"""
        ui = """
<button type="button" id="chart-scanner-trigger">📷 CHART SCANNER</button>
<div id="chart-scanner-overlay" role="dialog" aria-modal="true"><div class="chart-scanner-card">
<div class="chart-scanner-head"><h3>📷 Chart Scanner</h3><button type="button" class="chart-scanner-close" id="chart-scanner-close">CLOSE</button></div>
<div class="chart-scanner-input"><strong>Chart image দিন</strong>
<div class="chart-camera-row">
<label class="chart-source-btn">📷 ছবি তুলুন<input id="chart-scanner-camera" type="file" accept="image/*" capture="environment"></label>
<label class="chart-source-btn gallery">🖼️ গ্যালারি<input id="chart-scanner-gallery" type="file" accept="image/*"></label>
</div>
<input id="chart-scanner-file" type="file" accept="image/*" style="display:none">
<img id="chart-scanner-preview" alt="Chart preview"><button type="button" class="chart-scan-btn" id="chart-scanner-analyze">ANALYZE CHART</button></div>
<div id="chart-scanner-result"></div><div class="chart-scanner-note">এটি independent visual scanner। এটি বর্তমান v2.1 tick strategy পরিবর্তন বা override করে না।</div>
</div></div>
<script>
(()=>{const t=document.getElementById('chart-scanner-trigger');if(!t)return;const o=document.getElementById('chart-scanner-overlay'),c=document.getElementById('chart-scanner-close'),cam=document.getElementById('chart-scanner-camera'),gal=document.getElementById('chart-scanner-gallery'),f=document.getElementById('chart-scanner-file'),p=document.getElementById('chart-scanner-preview'),b=document.getElementById('chart-scanner-analyze'),r=document.getElementById('chart-scanner-result');let selected=null;const esc=v=>String(v??'—').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));t.onclick=()=>o.classList.add('open');c.onclick=()=>o.classList.remove('open');o.onclick=e=>{if(e.target===o)o.classList.remove('open')};function choose(file){if(!file)return;selected=file;f.value='';p.src=URL.createObjectURL(file);p.style.display='block';r.innerHTML=''}cam.onchange=()=>choose(cam.files?.[0]);gal.onchange=()=>choose(gal.files?.[0]);b.onclick=async()=>{if(!selected){r.innerHTML='<div class="chart-scan-result">প্রথমে 📷 ছবি তুলুন অথবা 🖼️ গ্যালারি থেকে ছবি নিন।</div>';return}b.disabled=true;b.textContent='ANALYZING…';r.innerHTML='<div class="chart-scan-result">Chart বিশ্লেষণ করা হচ্ছে…</div>';try{const fd=new FormData();fd.append('chart',selected,selected.name||'chart.jpg');fd.append('mode',document.getElementById('mode')?.value||'real');fd.append('pair',document.getElementById('pair')?.value||'');const q=await fetch('/chart-scanner',{method:'POST',body:fd,credentials:'same-origin'}),d=await q.json();if(!q.ok||!d.ok)throw Error(d.error||'Scanner failed');r.innerHTML=`<div class="chart-scan-result"><div class="chart-scan-signal">${esc(d.signal)}</div><div class="chart-scan-meta"><div><b>Signal Time</b><br>${esc(d.signal_time_bd)}</div><div><b>Confidence</b><br>${esc(d.confidence)}%</div><div><b>Trend</b><br>${esc(d.trend)}</div><div><b>Risk</b><br>${esc(d.risk)}</div></div><p><b>Reason:</b> ${esc(d.reason)}</p></div>`}catch(e){r.innerHTML=`<div class="chart-scan-result">${esc(e.message)}</div>`}finally{b.disabled=false;b.textContent='ANALYZE CHART'}}})();
</script>
"""
        html = html.replace("</head>", css + "</head>", 1)
        if '<div class="auto-row">' in html:
            html = html.replace('<div class="auto-row">', '<div class="auto-row">' + ui, 1)
        else:
            html = html.replace("</body>", ui + "</body>", 1)
        response.set_data(html)
        return response
