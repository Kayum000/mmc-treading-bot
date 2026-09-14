(() => {
  'use strict';
  // Non-invasive UI layer: score rendering, Bengali reason fallback, and nav state only.

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));

  const scoreBucket = (score) => {
    const n = Number(score);
    if (!Number.isFinite(n) || n <= 0) return ['NO_SCORE', 'কোনো স্কোর নেই'];
    if (n >= 80) return ['STRONG', 'খুব শক্তিশালী'];
    if (n >= 65) return ['GOOD', 'ভালো'];
    return ['WEAK', 'দুর্বল'];
  };

  const scoreFromResult = (result) => {
    const direct = Number(result?.signal_score ?? result?.score);
    if (Number.isFinite(direct)) return Math.max(0, Math.min(100, Math.round(direct)));
    const confidence = Number(result?.confidence);
    return Number.isFinite(confidence) ? Math.max(0, Math.min(100, Math.round(confidence * 100))) : 0;
  };

  function renderScore(result) {
    const container = document.getElementById('result-container');
    if (!container || !result) return;
    const body = container.querySelector('.card-body');
    if (!body) return;

    const score = scoreFromResult(result);
    const current = body.querySelector('#signal-score-box');
    if (current && Number(current.dataset.score) === score) return;

    const [bucket, bucketBn] = scoreBucket(score);
    const box = current || document.createElement('div');
    box.id = 'signal-score-box';
    box.dataset.score = String(score);
    box.innerHTML = `
      <div class="score-title"><span>📊 SIGNAL SCORE</span><b>${score}/100</b></div>
      <div class="score-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${score}">
        <i style="width:${score}%"></i>
      </div>
      <div class="score-meta"><span>${esc(bucket)}</span><strong>${esc(bucketBn)}</strong></div>
    `;
    if (!current) body.appendChild(box);
  }

  function translateVisibleReason() {
    const nodes = document.querySelectorAll('#result-container .reason, #result-container .reason strong');
    const replacements = [
      ['Score reached threshold but MTF, trigger, or structure confirmation conflicted', 'স্কোর প্রয়োজনীয় সীমায় পৌঁছেছে, কিন্তু MTF, ট্রিগার অথবা মার্কেট-স্ট্রাকচার কনফার্মেশনের মধ্যে অসামঞ্জস্য পাওয়া গেছে।'],
      ['Insufficient or conflicting confirmation', 'যথেষ্ট কনফার্মেশন পাওয়া যায়নি অথবা কনফার্মেশনগুলোর মধ্যে অসামঞ্জস্য রয়েছে।'],
      ['run confirmation absent', 'প্রয়োজনীয় প্রাইস-রান কনফার্মেশন পাওয়া যায়নি।'],
      ['quote pressure unavailable', 'কোট-প্রেশার ডাটা পাওয়া যাচ্ছে না।'],
      ['run and pressure are not aligned', 'প্রাইস-রান ও প্রেশার একই দিকে কনফার্ম করছে না।'],
    ];
    nodes.forEach((node) => {
      let text = node.textContent || '';
      replacements.forEach(([from, to]) => { text = text.replace(from, to); });
      if (node.textContent !== text) node.textContent = text;
    });
  }

  function injectStyles() {
    if (document.getElementById('dashboard-functional-style')) return;
    const style = document.createElement('style');
    style.id = 'dashboard-functional-style';
    style.textContent = `
      #signal-score-box{margin-top:12px;padding:11px 12px;border:1px solid #164a76;border-radius:9px;background:linear-gradient(180deg,#081f37,#06172a);contain:layout paint}
      #signal-score-box .score-title{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:10px;color:#74a8cf;font-weight:800}
      #signal-score-box .score-title b{font-family:var(--mono);font-size:18px;color:#f3f8ff}
      #signal-score-box .score-track{height:7px;margin:8px 0 6px;border-radius:999px;background:#102f4b;overflow:hidden}
      #signal-score-box .score-track i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,#1678ee,#20d6a2)}
      #signal-score-box .score-meta{display:flex;justify-content:space-between;gap:10px;font-size:9px;color:#6e8ca7}
      #signal-score-box .score-meta strong{color:#d7e9f8}
      .side-nav a[data-dashboard-nav-active="1"]{background:linear-gradient(90deg,#0759c9,#1268d9)!important;border-color:#1377ee!important;color:#fff!important}
    `;
    document.head.appendChild(style);
  }

  function setupNavigation() {
    const links = Array.from(document.querySelectorAll('.side-nav a[href^="#"]'));
    if (!links.length) return;
    const activate = (link) => {
      links.forEach((item) => {
        const active = item === link;
        item.classList.toggle('active', active);
        if (active) item.dataset.dashboardNavActive = '1';
        else delete item.dataset.dashboardNavActive;
      });
    };
    links.forEach((link) => {
      link.addEventListener('click', (event) => {
        const id = link.getAttribute('href')?.slice(1);
        const target = id ? document.getElementById(id) : null;
        if (!target) return;
        event.preventDefault();
        activate(link);
        target.scrollIntoView({behavior: 'smooth', block: 'start'});
        history.replaceState(null, '', `#${id}`);
      });
    });
    const initial = window.location.hash.slice(1);
    if (initial) {
      const link = links.find((item) => item.getAttribute('href') === `#${initial}`);
      if (link) activate(link);
    }
  }

  function observeResult() {
    const container = document.getElementById('result-container');
    if (!container) return;
    const apply = () => {
      const result = window.__mmcLastResult;
      if (result) renderScore(result);
      translateVisibleReason();
    };
    const observer = new MutationObserver(() => apply());
    observer.observe(container, {childList: true, subtree: true, characterData: true});

    const tryWrap = () => {
      const original = window.renderResult;
      if (typeof original !== 'function' || original.__mmcWrapped) return Boolean(original);
      const wrapped = function(result) {
        window.__mmcLastResult = result;
        const value = original.apply(this, arguments);
        renderScore(result);
        translateVisibleReason();
        return value;
      };
      wrapped.__mmcWrapped = true;
      window.renderResult = wrapped;
      return true;
    };
    if (!tryWrap()) {
      const timer = setInterval(() => { if (tryWrap()) clearInterval(timer); }, 50);
      setTimeout(() => clearInterval(timer), 10000);
    }
    apply();
  }

  function start() {
    injectStyles();
    setupNavigation();
    observeResult();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
