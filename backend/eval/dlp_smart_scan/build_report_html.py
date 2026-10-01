#!/usr/bin/env python3
"""Build a self-contained HTML report from a smart-scan eval JSON report.

Usage:
  python eval/dlp_smart_scan/build_report_html.py \\
    --report ../reports/run-20260711-fa-policy-286.json \\
    --out ../reports/dlp-smart-scan-report.html

Opens offline in any browser (data is embedded; no server needed).
RTL Persian UI, written for non-technical readers.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


TEMPLATE = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>گزارش آزمون امنیت محتوا (DLP)</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/vazirmatn@33.003/Vazirmatn-font-face.css"/>
<style>
  :root {
    --bg: #0b1220;
    --panel: #121a2b;
    --panel2: #182235;
    --border: #243049;
    --text: #e8eef9;
    --muted: #93a0b8;
    --ok: #22c55e;
    --miss: #f43f5e;
    --public: #38bdf8;
    --confidential: #f59e0b;
    --restricted: #ef4444;
    --accent: #818cf8;
    --chip: #1e293b;
    --font: "Vazirmatn", "Segoe UI", Tahoma, system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: var(--font);
    background: radial-gradient(1200px 600px at 90% -10%, #1a2744 0%, var(--bg) 55%);
    color: var(--text);
    line-height: 1.75;
  }
  header {
    padding: 28px 24px 12px;
    max-width: 1100px;
    margin: 0 auto;
  }
  header h1 {
    margin: 0 0 8px;
    font-size: 1.55rem;
    letter-spacing: -0.02em;
    font-weight: 800;
  }
  header .sub { color: var(--muted); font-size: 0.95rem; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 0 24px 48px; }
  .intro {
    background: linear-gradient(180deg, var(--panel), var(--panel2));
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px 18px;
    margin: 14px 0 8px;
    color: var(--muted);
    font-size: 0.95rem;
  }
  .intro strong { color: var(--text); }
  .legend {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 10px;
    margin: 14px 0 8px;
  }
  .legend-item {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 14px;
  }
  .legend-item .title { font-weight: 700; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
  .legend-item p { margin: 0; color: var(--muted); font-size: 0.88rem; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin: 18px 0 22px;
  }
  .card {
    background: linear-gradient(180deg, var(--panel), var(--panel2));
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 14px 16px;
  }
  .card .label { color: var(--muted); font-size: 0.82rem; }
  .card .value { font-size: 1.4rem; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .card .value.ok { color: var(--ok); }
  .card .value.miss { color: var(--miss); }
  .card .hint { color: var(--muted); font-size: 0.78rem; margin-top: 4px; }
  h2 {
    margin: 28px 0 10px;
    font-size: 1.12rem;
    border-inline-start: 3px solid var(--accent);
    padding-inline-start: 10px;
  }
  .section-help {
    color: var(--muted);
    font-size: 0.9rem;
    margin: -4px 0 12px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }
  th, td {
    border-bottom: 1px solid var(--border);
    padding: 9px 10px;
    text-align: start;
  }
  th { color: var(--muted); font-weight: 600; font-size: 0.8rem; }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin: 10px 0 14px;
  }
  input[type="search"], select, button {
    font-family: var(--font);
  }
  input[type="search"], select {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 10px;
    padding: 8px 12px;
    min-width: 160px;
    font: inherit;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--chip);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 2px 8px;
    font-size: 0.75rem;
    color: var(--muted);
    margin: 1px;
  }
  .badge {
    display: inline-block;
    border-radius: 8px;
    padding: 3px 9px;
    font-size: 0.78rem;
    font-weight: 700;
  }
  .badge.ok { background: rgba(34,197,94,.15); color: var(--ok); }
  .badge.miss { background: rgba(244,63,94,.15); color: var(--miss); }
  .badge.public { background: rgba(56,189,248,.15); color: var(--public); }
  .badge.confidential { background: rgba(245,158,11,.15); color: var(--confidential); }
  .badge.restricted { background: rgba(239,68,68,.15); color: var(--restricted); }
  .row-card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
  }
  .row-card.miss { border-color: rgba(244,63,94,.45); }
  .row-card .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
  }
  .row-card .id { font-family: ui-monospace, Consolas, monospace; font-size: 0.82rem; color: var(--accent); direction: ltr; }
  .block-label {
    color: var(--muted);
    font-size: 0.8rem;
    margin: 10px 0 4px;
    font-weight: 600;
  }
  .text-box, .guidance-box, .reason-box {
    background: #0a101c;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.92rem;
  }
  .guidance-box {
    border-color: rgba(129,140,248,.4);
    background: rgba(129,140,248,.06);
  }
  .spans {
    font-family: ui-monospace, Consolas, monospace;
    font-size: 0.82rem;
    color: #fde68a;
    direction: ltr;
    text-align: left;
  }
  .tabs { display: flex; gap: 6px; margin: 8px 0 14px; flex-wrap: wrap; }
  .tab {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 999px;
    padding: 8px 14px;
    cursor: pointer;
    font-size: 0.9rem;
    font: inherit;
  }
  .tab.active {
    color: var(--text);
    border-color: var(--accent);
    background: rgba(129,140,248,.12);
  }
  .hidden { display: none !important; }
  footer {
    color: var(--muted);
    font-size: 0.82rem;
    margin-top: 32px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .conf td, .conf th { text-align: center; }
  .conf td:first-child, .conf th:first-child { text-align: start; }
  .plain-num { font-variant-numeric: tabular-nums; }
  .verdict {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    align-items: center;
    margin: 8px 0 4px;
    font-size: 0.9rem;
  }
  .verdict .arrow { color: var(--muted); }
  code { font-family: ui-monospace, Consolas, monospace; font-size: 0.88em; direction: ltr; display: inline-block; }
</style>
</head>
<body>
<header>
  <h1>گزارش آزمون امنیت محتوا</h1>
  <div class="sub" id="subtitle"></div>
</header>
<div class="wrap">
  <div class="intro">
    <strong>این گزارش چیست؟</strong>
    ما چند صد پیام نمونه (مثل پیام چت) به «هوش مصنوعیِ تشخیص حساسیت» دادیم و دیدیم
    سطح امنیتی را درست تشخیص می‌دهد یا نه. هدف: قبل از ارسال به مدل‌های بیرونی،
    اطلاعات حساس شرکت (رمز، حقوق، قرارداد، اطلاعات مشتری…) کمتر لو برود.
    <br/><br/>
    <strong>چطور بخوانیم؟</strong>
    عدد «درصد تشخیص درست» هرچه بالاتر باشد بهتر است. تب «اشتباه‌ها» مواردی است
    که سیستم سطح را اشتباه فهمیده — برای بهبود قوانین و مدل مفید است.
  </div>

  <div class="legend">
    <div class="legend-item">
      <div class="title"><span class="badge public">عمومی</span></div>
      <p>محتوای بی‌خطر یا فقط «دربارهٔ» یک موضوع حساس — بدون عدد/رمز واقعی. معمولاً آزاد است.</p>
    </div>
    <div class="legend-item">
      <div class="title"><span class="badge confidential">محرمانه</span></div>
      <p>اطلاعات داخلی مهم که بیرون شرکت نباید پخش شود؛ نیاز به احتیاط یا تأیید دارد.</p>
    </div>
    <div class="legend-item">
      <div class="title"><span class="badge restricted">بسیار حساس</span></div>
      <p>رمز، کلید API، حقوق و ارقام مالی مشتری، دادهٔ پرسنلی حساس — معمولاً باید متوقف یا محدود شود.</p>
    </div>
  </div>

  <div class="grid" id="kpis"></div>

  <div class="tabs">
    <button class="tab active" data-tab="overview" type="button">خلاصه نتایج</button>
    <button class="tab" data-tab="guidance" type="button">قوانین اختصاصی شرکت</button>
    <button class="tab" data-tab="misses" type="button">موارد اشتباه</button>
    <button class="tab" data-tab="all" type="button">همهٔ نمونه‌ها</button>
  </div>

  <section id="panel-overview">
    <h2>عملکرد در هر سطح حساسیت</h2>
    <p class="section-help">
      «پوشش» یعنی از نمونه‌های واقعی آن سطح چندتایش را پیدا کرده.
      «دقت وقتی گفته» یعنی وقتی این سطح را اعلام کرده، چند درصد درست بوده.
      «امتیاز کلی» ترکیب این دو است (نزدیک ۱۰۰٪ بهتر).
    </p>
    <div class="card"><table id="per-class"></table></div>

    <h2>جدول جابه‌جایی (کجا اشتباه کرده؟)</h2>
    <p class="section-help">
      سطر = پاسخ درست مورد انتظار · ستون = چیزی که سیستم گفته.
      عدد روی قطر اصلی (هم‌نام) = درست. بقیه = اشتباه (مثلاً بسیار حساس را محرمانه دیده).
    </p>
    <div class="card"><table class="conf" id="confusion"></table></div>

    <h2>نتیجه به تفکیک گروه</h2>
    <p class="section-help">هر گروه نوع خاصی از پیام‌هاست (فارسی/انگلیسی، فقط موضوع، رمز واقعی، قوانین شرکت…).</p>
    <div class="card"><table id="slices"></table></div>
  </section>

  <section id="panel-guidance" class="hidden">
    <h2>نمونه‌هایی با قوانین اختصاصی شرکت</h2>
    <p class="section-help">
      بعضی شرکت‌ها قانون اضافه می‌نویسند (مثلاً «نام پروژه X محرمانه است»).
      اینجا می‌بینید سیستم با آن قانون چطور عمل کرده.
    </p>
    <div id="guidance-list"></div>
  </section>

  <section id="panel-misses" class="hidden">
    <h2>مواردی که سیستم اشتباه تشخیص داد</h2>
    <p class="section-help">برای هر مورد: پیام نمونه، سطح درست، سطح تشخیص‌داده‌شده، و توضیح سیستم.</p>
    <div id="miss-list"></div>
  </section>

  <section id="panel-all" class="hidden">
    <h2>همهٔ نمونه‌های آزمون</h2>
    <div class="toolbar">
      <input type="search" id="q" placeholder="جستجو در متن یا توضیح…"/>
      <select id="filter-status">
        <option value="">همه وضعیت‌ها</option>
        <option value="ok">فقط درست</option>
        <option value="miss">فقط اشتباه</option>
      </select>
      <select id="filter-cat">
        <option value="">همه سطوح درست</option>
        <option value="public">عمومی</option>
        <option value="confidential">محرمانه</option>
        <option value="restricted">بسیار حساس</option>
      </select>
      <select id="filter-tag">
        <option value="">همه برچسب‌ها</option>
      </select>
      <span class="chip" id="count-chip"></span>
    </div>
    <div id="all-list"></div>
  </section>

  <footer>
    گزارش آفلاین از نتیجهٔ آزمون «اسکن هوشمند امنیت محتوا».
    این فقط بخش هوش مصنوعیِ دسته‌بندی است؛ قوانین متنی/عبارت‌های ثابت جداگانه هم در محصول فعال‌اند.
  </footer>
</div>

<script id="report-data" type="application/json">__REPORT_JSON__</script>
<script>
const REPORT = JSON.parse(document.getElementById('report-data').textContent);
const rows = REPORT.rows || [];
const metrics = REPORT.metrics || {};

const CAT = {
  public: 'عمومی',
  confidential: 'محرمانه',
  restricted: 'بسیار حساس',
  fail_open: 'بدون پاسخ',
};
const TAG_FA = {
  'lang:en': 'انگلیسی',
  'lang:fa': 'فارسی',
  'tag:topic_only': 'فقط موضوع (بدون مقدار واقعی)',
  'tag:value_present': 'با مقدار واقعی (رمز، عدد، نام…)',
  'tag:clean': 'پیام بی‌خطر',
  'tag:secret': 'رمز / کلید / توکن',
  'tag:pii': 'اطلاعات شخصی',
  'tag:semantic': 'حساسیت معنایی (بدون شکل رمز)',
  'tag:guidance': 'با قانون اختصاصی شرکت',
  hard: 'سخت',
  adversarial: 'گمراه‌کننده',
  clean: 'بی‌خطر',
  secret: 'رمز',
  pii: 'شخصی',
  semantic: 'معنایی',
  guidance: 'قانون شرکت',
  topic_only: 'فقط موضوع',
  value_present: 'مقدار واقعی',
  financial: 'مالی',
  customer: 'مشتری',
  salary: 'حقوق',
  health: 'سلامت',
  legal: 'حقوقی',
  deal: 'معامله',
  mna: 'ادغام/خرید',
  pricing: 'قیمت‌گذاری',
  sales: 'فروش',
  codename: 'نام رمزی پروژه',
  edge: 'لبه',
  fa_policy: 'سیاست فارسی کامل',
  slack: 'اسلک',
  stripe: 'استرایپ',
};
const TAG_SELECT_FA = {
  hard: 'سخت',
  adversarial: 'گمراه‌کننده',
  clean: 'بی‌خطر',
  secret: 'رمز/کلید',
  pii: 'اطلاعات شخصی',
  semantic: 'معنایی',
  guidance: 'قانون شرکت',
  topic_only: 'فقط موضوع',
  value_present: 'مقدار واقعی',
  financial: 'مالی',
  customer: 'مشتری',
  salary: 'حقوق',
  health: 'سلامت',
  legal: 'حقوقی',
  deal: 'معامله',
  mna: 'ادغام/خرید',
  pricing: 'قیمت‌گذاری',
  sales: 'فروش',
  codename: 'نام رمزی',
  edge: 'لبه',
  fa_policy: 'سیاست فارسی',
  slack: 'اسلک',
  stripe: 'استرایپ',
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function faNum(n, digits) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const x = Number(n);
  const s = digits == null ? String(x) : x.toFixed(digits);
  return s.replace(/\d/g, d => '۰۱۲۳۴۵۶۷۸۹'[d]);
}
function pct(x) {
  if (x == null || Number.isNaN(Number(x))) return '—';
  return faNum(Number(x) * 100, 1) + '٪';
}
function catLabel(c) {
  return CAT[c] || c || '—';
}
function catBadge(c) {
  if (!c) return '<span class="badge miss">بدون پاسخ</span>';
  const cls = (c === 'fail_open') ? 'miss' : c;
  return `<span class="badge ${esc(cls)}">${esc(catLabel(c))}</span>`;
}
function statusBadge(ok) {
  return ok
    ? '<span class="badge ok">درست ✓</span>'
    : '<span class="badge miss">اشتباه ✗</span>';
}
function tagLabel(t) {
  return TAG_FA[t] || TAG_SELECT_FA[t] || t;
}
function tagsHtml(tags) {
  return (tags || []).map(t => `<span class="chip">${esc(tagLabel(t))}</span>`).join('');
}
function fmtDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return new Intl.DateTimeFormat('fa-IR', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Tehran'
    }).format(d);
  } catch (_) {
    return iso;
  }
}
function rowCard(r) {
  const miss = !r.correct;
  const guidance = r.guidance_prompt
    ? `<div class="block-label">قانون اختصاصی شرکت در این نمونه</div><div class="guidance-box">${esc(r.guidance_prompt)}</div>`
    : '';
  const lang = r.lang === 'fa' ? 'فارسی' : (r.lang === 'en' ? 'انگلیسی' : (r.lang || '—'));
  const ms = r.latency_ms != null ? faNum(Math.round(r.latency_ms)) + ' میلی‌ثانیه' : '—';
  return `<article class="row-card ${miss ? 'miss' : ''}">
    <div class="meta">
      ${statusBadge(r.correct)}
      <span class="chip">${esc(lang)}</span>
      <span class="chip">${esc(ms)}</span>
      ${tagsHtml(r.tags)}
      <span class="id" title="شناسه فنی نمونه">${esc(r.id)}</span>
    </div>
    <div class="verdict">
      <span>سطح درست: ${catBadge(r.gold_category)}</span>
      <span class="arrow">← سیستم گفت →</span>
      <span>${catBadge(r.predicted)}</span>
    </div>
    ${guidance}
    <div class="block-label">متن پیام (نمونه آزمون)</div>
    <div class="text-box">${esc(r.text_preview)}</div>
    <div class="block-label">توضیح سیستم</div>
    <div class="reason-box">${esc(r.reason || '—')}</div>
    <div class="block-label">عبارت‌هایی که برجسته کرده</div>
    <div class="spans">${esc((r.spans && r.spans.length) ? r.spans.join(' · ') : '—')}</div>
  </article>`;
}

// KPIs
const acc = metrics.accuracy_pct ?? 0;
const n = metrics.n ?? rows.length;
const correct = metrics.correct ?? 0;
const missN = (REPORT.misses && REPORT.misses.length) || Math.max(0, n - correct);
document.getElementById('subtitle').textContent =
  `تاریخ آزمون: ${fmtDate(REPORT.generated_at)} · تعداد نمونه: ${faNum(n)}`;

const sliceAcc = (key) => {
  const s = (metrics.slices || {})[key];
  if (!s || s.accuracy == null) return '—';
  return faNum(s.accuracy * 100, 1) + '٪';
};

document.getElementById('kpis').innerHTML = `
  <div class="card">
    <div class="label">درصد تشخیص درست</div>
    <div class="value ok">${esc(faNum(acc, 1))}٪</div>
    <div class="hint">از هر ۱۰۰ پیام، حدود ${esc(faNum(Math.round(acc)))} تا درست</div>
  </div>
  <div class="card">
    <div class="label">تشخیص درست</div>
    <div class="value plain-num">${esc(faNum(correct))} از ${esc(faNum(n))}</div>
    <div class="hint">تعداد نمونه‌های موفق</div>
  </div>
  <div class="card">
    <div class="label">اشتباه</div>
    <div class="value miss plain-num">${esc(faNum(missN))}</div>
    <div class="hint">برای بررسی در تب «اشتباه‌ها»</div>
  </div>
  <div class="card">
    <div class="label">بدون پاسخ</div>
    <div class="value plain-num">${esc(faNum(metrics.fail_open ?? 0))}</div>
    <div class="hint">سیستم جوابی نداد (خطا/تایم‌اوت)</div>
  </div>
  <div class="card">
    <div class="label">قوانین اختصاصی شرکت</div>
    <div class="value">${esc(sliceAcc('tag:guidance'))}</div>
    <div class="hint">نمونه‌هایی با سیاست سفارشی</div>
  </div>
  <div class="card">
    <div class="label">حساسیت معنایی</div>
    <div class="value">${esc(sliceAcc('tag:semantic'))}</div>
    <div class="hint">بدون شکل رمز کلاسیک (مثل حقوق مشتری)</div>
  </div>
`;

// Per-class — plain columns
const pc = metrics.per_class || {};
document.getElementById('per-class').innerHTML = `
  <tr>
    <th>سطح</th>
    <th>دقت وقتی گفته</th>
    <th>پوشش نمونه‌ها</th>
    <th>امتیاز کلی</th>
    <th>تعداد نمونه</th>
  </tr>
  ${['public','confidential','restricted'].map(c => {
    const x = pc[c] || {};
    return `<tr>
      <td>${catBadge(c)}</td>
      <td class="plain-num">${pct(x.precision)}</td>
      <td class="plain-num">${pct(x.recall)}</td>
      <td class="plain-num">${pct(x.f1)}</td>
      <td class="plain-num">${faNum(x.support ?? 0)}</td>
    </tr>`;
  }).join('')}
`;

// Confusion
const conf = metrics.confusion || {};
const preds = ['public','confidential','restricted','fail_open'];
document.getElementById('confusion').innerHTML = `
  <tr><th>درست ＼ تشخیص</th>${preds.map(p=>`<th>${esc(catLabel(p))}</th>`).join('')}</tr>
  ${['public','confidential','restricted'].map(g => {
    const row = conf[g] || {};
    return `<tr><th>${esc(catLabel(g))}</th>${preds.map(p=>`<td class="plain-num">${faNum(row[p]??0)}</td>`).join('')}</tr>`;
  }).join('')}
`;

// Slices
const slices = metrics.slices || {};
document.getElementById('slices').innerHTML = `
  <tr><th>گروه</th><th>تعداد</th><th>درصد درست</th></tr>
  ${Object.entries(slices).map(([k,v]) => {
    const a = v.accuracy == null ? '—' : faNum(v.accuracy * 100, 1) + '٪';
    return `<tr><td>${esc(tagLabel(k))}</td><td class="plain-num">${faNum(v.n??0)}</td><td class="plain-num">${a}</td></tr>`;
  }).join('')}
`;

// Guidance list
const gRows = rows.filter(r => r.guidance_prompt);
document.getElementById('guidance-list').innerHTML =
  gRows.length ? gRows.map(rowCard).join('') :
  '<p style="color:var(--muted)">در این گزارش نمونه‌ای با قانون اختصاصی نبود.</p>';

// Misses
const misses = REPORT.misses || rows.filter(r => !r.correct);
document.getElementById('miss-list').innerHTML =
  misses.length ? misses.map(rowCard).join('') :
  '<p style="color:var(--ok)">هیچ اشتباهی ثبت نشده — عالی 🎉</p>';

// Tag filter options
const allTags = [...new Set(rows.flatMap(r => r.tags || []))].sort();
const tagSel = document.getElementById('filter-tag');
allTags.forEach(t => {
  const o = document.createElement('option');
  o.value = t;
  o.textContent = TAG_SELECT_FA[t] || t;
  tagSel.appendChild(o);
});

function renderAll() {
  const q = document.getElementById('q').value.trim().toLowerCase();
  const st = document.getElementById('filter-status').value;
  const cat = document.getElementById('filter-cat').value;
  const tag = document.getElementById('filter-tag').value;
  let list = rows.slice();
  if (st === 'ok') list = list.filter(r => r.correct);
  if (st === 'miss') list = list.filter(r => !r.correct);
  if (cat) list = list.filter(r => r.gold_category === cat);
  if (tag) list = list.filter(r => (r.tags||[]).includes(tag));
  if (q) {
    list = list.filter(r =>
      (r.id||'').toLowerCase().includes(q) ||
      (r.text_preview||'').toLowerCase().includes(q) ||
      (r.guidance_prompt||'').toLowerCase().includes(q) ||
      (r.reason||'').toLowerCase().includes(q)
    );
  }
  document.getElementById('count-chip').textContent = `${faNum(list.length)} مورد نمایش`;
  document.getElementById('all-list').innerHTML = list.map(rowCard).join('') ||
    '<p style="color:var(--muted)">با این فیلتر چیزی پیدا نشد.</p>';
}
['q','filter-status','filter-cat','filter-tag'].forEach(id => {
  document.getElementById(id).addEventListener('input', renderAll);
  document.getElementById(id).addEventListener('change', renderAll);
});
renderAll();

// Tabs
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const name = btn.dataset.tab;
    ['overview','guidance','misses','all'].forEach(p => {
      document.getElementById('panel-'+p).classList.toggle('hidden', p !== name);
    });
  });
});
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to eval JSON report",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output HTML path (default: next to report)",
    )
    args = ap.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    out = args.out or args.report.with_suffix(".html")
    # Embed JSON safely inside <script type="application/json">
    payload = json.dumps(report, ensure_ascii=False)
    # Prevent </script> breakouts in embedded JSON
    payload = payload.replace("<", "\\u003c")
    html_out = TEMPLATE.replace("__REPORT_JSON__", payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"wrote {out.resolve()}")
    print(
        f"  accuracy={report.get('metrics', {}).get('accuracy_pct')}% "
        f"N={report.get('metrics', {}).get('n')} "
        f"rows={len(report.get('rows') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
