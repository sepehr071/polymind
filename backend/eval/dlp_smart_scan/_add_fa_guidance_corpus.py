"""Append full-Persian custom-guidance eval rows (policy + chat in Persian)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus.jsonl"

# Full Persian guidance_prompt + Persian user text.
# HIT = policy phrase present → restricted/confidential
# MISS = same policy, phrase absent → public
ROWS = [
    # --- Codename / project ---
    {
        "id": "fa-guidance-fa-orion-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "codename"],
        "guidance_prompt": (
            "سیاست محرمانگی فضای کاری: هر اشاره‌ای به اسم رمز پروژه «اوریون-۹» یا نام مستعار "
            "«بندرقرمز» محدود (restricted) است. بحث عمومی دربارهٔ لانچ بدون ذکر این نام‌ها مجاز است. "
            "در spans همان رشتهٔ فارسی/لاتین موجود در متن را برگردان."
        ),
        "text": "وضعیت شیفت: اوریون-۹ از ریویو امنیتی گذشت و مرحلهٔ بعد بندرقرمز است؛ بیرون از کانال عملیات ننویسید.",
        "notes": "Persian policy + both policy phrases present",
    },
    {
        "id": "fa-guidance-fa-orion-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "codename"],
        "guidance_prompt": (
            "سیاست محرمانگی فضای کاری: هر اشاره‌ای به اسم رمز پروژه «اوریون-۹» یا نام مستعار "
            "«بندرقرمز» محدود (restricted) است. بحث عمومی دربارهٔ لانچ بدون ذکر این نام‌ها مجاز است. "
            "در spans همان رشتهٔ فارسی/لاتین موجود در متن را برگردان."
        ),
        "text": "فرآیند بازنشسته کردن اسم رمز پروژه‌ها بعد از لانچ عمومی چیست؟ لطفاً بدون مثال خاص توضیح بده.",
        "notes": "Same Persian policy; no listed codename in text",
    },
    {
        "id": "fa-guidance-fa-shahin-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "codename"],
        "guidance_prompt": (
            "نام برنامهٔ داخلی «شاهین کویر» محدود است. صحبت کلی دربارهٔ گسترش منطقه‌ای بدون این نام عمومی است. "
            "اگر «شاهین کویر» در پیام آمد، category=restricted و همان عبارت را در spans بگذار."
        ),
        "text": "کمیته گسترش: بودجهٔ شاهین کویر برای فاز جنوب فقط در کانال محدود بماند.",
        "notes": "Multi-word Persian initiative name present",
    },
    {
        "id": "fa-guidance-fa-shahin-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "codename"],
        "guidance_prompt": (
            "نام برنامهٔ داخلی «شاهین کویر» محدود است. صحبت کلی دربارهٔ گسترش منطقه‌ای بدون این نام عمومی است. "
            "اگر «شاهین کویر» در پیام آمد، category=restricted و همان عبارت را در spans بگذار."
        ),
        "text": "برای گسترش در جنوب کشور معمولاً چه آیتم‌های بودجه‌ای در کمیته بررسی می‌شود؟",
        "notes": "Regional expansion topic without initiative name",
    },
    # --- Client aliases (Persian labels) ---
    {
        "id": "fa-guidance-fa-client-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "customer"],
        "guidance_prompt": (
            "نام‌های مستعار مشتری «انار» و «سنگ‌ریزه» محدودند. بحث کلی دربارهٔ تمدید قرارداد مشتریان "
            "بدون ذکر این نام‌ها عمومی است. در صورت وجود، همان نام مستعار را در spans قرار بده."
        ),
        "text": "انار برای تمدید سه‌ساله ۱۸٪ تخفیف می‌خواهد؛ سنگ‌ریزه با قیمت لیست موافق است.",
        "notes": "Both Persian client aliases present",
    },
    {
        "id": "fa-guidance-fa-client-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "customer"],
        "guidance_prompt": (
            "نام‌های مستعار مشتری «انار» و «سنگ‌ریزه» محدودند. بحث کلی دربارهٔ تمدید قرارداد مشتریان "
            "بدون ذکر این نام‌ها عمومی است. در صورت وجود، همان نام مستعار را در spans قرار بده."
        ),
        "text": "چطور پیشنهاد تمدید چندساله برای مشتریان بزرگ بنویسیم بدون افشای نام حساب؟",
        "notes": "Renewal topic without aliases",
    },
    {
        "id": "fa-guidance-fa-client-hit-02",
        "lang": "fa",
        "gold_category": "confidential",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "customer"],
        "guidance_prompt": (
            "نام مستعار مشتری «زره‌پوش» محرمانه (confidential) است. صحبت دربارهٔ مشتریان بخش دفاعی "
            "بدون این نام مستعار عمومی است."
        ),
        "text": "لید این هفته: زره‌پوش درخواست دموی on-prem و SLA سخت‌گیرانه‌تر دارد.",
        "notes": "Persian alias present → confidential per policy",
    },
    {
        "id": "fa-guidance-fa-client-miss-02",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "customer"],
        "guidance_prompt": (
            "نام مستعار مشتری «زره‌پوش» محرمانه (confidential) است. صحبت دربارهٔ مشتریان بخش دفاعی "
            "بدون این نام مستعار عمومی است."
        ),
        "text": "آیا برای مشتریان بخش دفاعی باید دموی جدا و SLA سخت‌تر آماده کنیم؟",
        "notes": "Defense sector topic without alias",
    },
    # --- HR / facilities Persian phrases ---
    {
        "id": "fa-guidance-fa-hr-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "hr"],
        "guidance_prompt": (
            "عبارت دقیق «توقف جذب نیروی فصل زمستان» استراتژی منابع انسانی محدود است. "
            "صحبت کلی دربارهٔ کند شدن استخدام بدون این عبارت عمومی است. "
            "اگر عبارت کامل آمد، restricted و همان عبارت را span کن."
        ),
        "text": "بستهٔ مدیران هنوز توقف جذب نیروی فصل زمستان را برای مهندسی و پشتیبانی غیرقابل‌مذاکره می‌داند.",
        "notes": "Exact multi-word HR phrase present",
    },
    {
        "id": "fa-guidance-fa-hr-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "hr"],
        "guidance_prompt": (
            "عبارت دقیق «توقف جذب نیروی فصل زمستان» استراتژی منابع انسانی محدود است. "
            "صحبت کلی دربارهٔ کند شدن استخدام بدون این عبارت عمومی است. "
            "اگر عبارت کامل آمد، restricted و همان عبارت را span کن."
        ),
        "text": "آیا امسال استخدام بیرونی در مهندسی کند می‌شود یا فقط قراردادهای پیمانکاری محدودتر می‌گردد؟",
        "notes": "Hiring slowdown without exact policy phrase",
    },
    {
        "id": "fa-guidance-fa-facilities-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "عبارت «جابجایی رک‌های تهران» برنامه‌ریزی امکانات محدود است. "
            "بحث عمومی دربارهٔ جابجایی دیتاسنتر بدون این عبارت مجاز است."
        ),
        "text": "امکانات: جابجایی رک‌های تهران دو هفته عقب افتاد چون کابل‌کشی برق دیر شد.",
        "notes": "Exact facilities phrase present",
    },
    {
        "id": "fa-guidance-fa-facilities-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "عبارت «جابجایی رک‌های تهران» برنامه‌ریزی امکانات محدود است. "
            "بحث عمومی دربارهٔ جابجایی دیتاسنتر بدون این عبارت مجاز است."
        ),
        "text": "چک‌لیست جابجایی رک بین سایت‌های کولوكیشن در خاورمیانه چیست؟",
        "notes": "Generic colo move checklist",
    },
    # --- Vendor / product Persian ---
    {
        "id": "fa-guidance-fa-vendor-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "نام فروشنده «نکس‌لایف» در ایمیل و چت خروجی محدود است. مقایسهٔ کلی فروشندگان SIEM "
            "بدون نام بردن از نکس‌لایف عمومی است."
        ),
        "text": "پیشنهاد قیمت نکس‌لایف را فقط در پوشهٔ خریداری داخلی نگه دارید و فوروارد خارجی نکنید.",
        "notes": "Persian vendor name present",
    },
    {
        "id": "fa-guidance-fa-vendor-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "نام فروشنده «نکس‌لایف» در ایمیل و چت خروجی محدود است. مقایسهٔ کلی فروشندگان SIEM "
            "بدون نام بردن از نکس‌لایف عمومی است."
        ),
        "text": "معیارهای ارزیابی فروشندگان SIEM از نظر پشتیبانی SOC و هزینهٔ چندساله چیست؟",
        "notes": "SIEM evaluation without vendor name",
    },
    {
        "id": "fa-guidance-fa-product-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "خط محصول «پرداخت سحابی» وقتی با این نام ذکر شود محدود است. "
            "سؤالات علمی دربارهٔ سحابی‌های نجومی عمومی‌اند و نباید اشتباهی محدود شوند."
        ),
        "text": "اسلاید فروش: قابلیت‌های جدید پرداخت سحابی را قبل از اعلام رسمی در کانال عمومی نگذارید.",
        "notes": "Product line name present",
    },
    {
        "id": "fa-guidance-fa-product-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "خط محصول «پرداخت سحابی» وقتی با این نام ذکر شود محدود است. "
            "سؤالات علمی دربارهٔ سحابی‌های نجومی عمومی‌اند و نباید اشتباهی محدود شوند."
        ),
        "text": "سحابی در اخترشناسی چیست و تلسکوپ‌ها چطور از آن تصویر می‌گیرند؟",
        "notes": "Astronomy false-friend; must stay public",
    },
    # --- Payroll / finance Persian phrases ---
    {
        "id": "fa-guidance-fa-payroll-hit-01",
        "lang": "fa",
        "gold_category": "confidential",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "hr"],
        "guidance_prompt": (
            "هر چیزی دربارهٔ «مهاجرت حقوق‌ودستمزد ایران» یا عبارت «موج کاهش حقوق» محرمانه است. "
            "بحث عمومی دربارهٔ سیستم‌های حقوق در شرکت‌های دیگر بدون این عبارات عمومی است."
        ),
        "text": "مهاجرت حقوق‌ودستمزد ایران به مرداد موکول شد؛ اعلام عمومی را با دقت هماهنگ کنید.",
        "notes": "Payroll migration phrase present → confidential",
    },
    {
        "id": "fa-guidance-fa-payroll-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "hr"],
        "guidance_prompt": (
            "هر چیزی دربارهٔ «مهاجرت حقوق‌ودستمزد ایران» یا عبارت «موج کاهش حقوق» محرمانه است. "
            "بحث عمومی دربارهٔ سیستم‌های حقوق در شرکت‌های دیگر بدون این عبارات عمومی است."
        ),
        "text": "شرکت‌های دیگر چطور مهاجرت سیستم حقوق را به کارکنان اطلاع می‌دهند؟",
        "notes": "Generic payroll migration communication",
    },
    {
        "id": "fa-guidance-fa-payroll-hit-02",
        "lang": "fa",
        "gold_category": "confidential",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "hr"],
        "guidance_prompt": (
            "هر چیزی دربارهٔ «مهاجرت حقوق‌ودستمزد ایران» یا عبارت «موج کاهش حقوق» محرمانه است. "
            "بحث عمومی دربارهٔ سیستم‌های حقوق در شرکت‌های دیگر بدون این عبارات عمومی است."
        ),
        "text": "شایعهٔ داخلی دربارهٔ موج کاهش حقوق را در چت عمومی تکرار نکنید تا اطلاع‌رسانی رسمی برسد.",
        "notes": "Second policy phrase present",
    },
    # --- R&D / partnership Persian ---
    {
        "id": "fa-guidance-fa-rd-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "اسم رمز تحقیقاتی «پرنده آبی» محدود است. صحبت دربارهٔ پایلوت‌های تحقیقاتی بدون این نام عمومی است. "
            "اگر «پرنده آبی» آمد، restricted کن و span همان عبارت باشد."
        ),
        "text": "نتایج آزمایشگاه برای پرنده آبی را تا ثبت پتنت در اسلاید عمومی نگذارید.",
        "notes": "Persian R&D codename present",
    },
    {
        "id": "fa-guidance-fa-rd-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "اسم رمز تحقیقاتی «پرنده آبی» محدود است. صحبت دربارهٔ پایلوت‌های تحقیقاتی بدون این نام عمومی است. "
            "اگر «پرنده آبی» آمد، restricted کن و span همان عبارت باشد."
        ),
        "text": "آیا می‌توان خلاصهٔ غیرتکنیکال از پایلوت تحقیقاتی latency را قبل از ثبت پتنت منتشر کرد؟",
        "notes": "R&D pilot topic without codename",
    },
    {
        "id": "fa-guidance-fa-deal-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "deal"],
        "guidance_prompt": (
            "همهٔ شرایط مربوط به شراکت «سدر» (قیمت، سهام، انحصار) محدود است. "
            "اگر نام سدر همراه عدد مالی یا مدت انحصار آمد، restricted کن و عبارات را span کن."
        ),
        "text": "شراکت سدر انحصار ۲۴ ماهه با حداقل تعهد ۱.۱ میلیون دلار دارد؛ فقط در اتاق معامله بماند.",
        "notes": "Named partnership + terms under Persian policy",
    },
    {
        "id": "fa-guidance-fa-deal-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "deal"],
        "guidance_prompt": (
            "همهٔ شرایط مربوط به شراکت «سدر» (قیمت، سهام، انحصار) محدود است. "
            "اگر نام سدر همراه عدد مالی یا مدت انحصار آمد، restricted کن و عبارات را span کن."
        ),
        "text": "در شراکت‌های استراتژیک معمولاً چه مواردی در بند انحصار و حداقل تعهد نوشته می‌شود؟",
        "notes": "Generic partnership structure; no Cedar/سدر",
    },
    # --- Security ops Persian ---
    {
        "id": "fa-guidance-fa-incident-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "کد حادثهٔ داخلی «قو سیاه» محدود است. بحث دربارهٔ قطعی سرویس بدون این کد عمومی است."
        ),
        "text": "یادداشت پل حادثه: علت ریشه‌ای قو سیاه هنوز پیش‌نویس است؛ نام مستعار را در اسلک عمومی ننویسید.",
        "notes": "Incident codename present",
    },
    {
        "id": "fa-guidance-fa-incident-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "کد حادثهٔ داخلی «قو سیاه» محدود است. بحث دربارهٔ قطعی سرویس بدون این کد عمومی است."
        ),
        "text": "بعد از قطعی جزئی دیروز، چه کسی مالک قالب postmortem برای اختلال API منطقه‌ای است؟",
        "notes": "Outage process without incident code",
    },
    # --- Mixed severity: confidential phrase ---
    {
        "id": "fa-guidance-fa-org-hit-01",
        "lang": "fa",
        "gold_category": "confidential",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "pii"],
        "guidance_prompt": (
            "عبارت «لیست آن‌کال نوروز» محرمانه است چون شامل برنامهٔ حضور افراد می‌شود. "
            "صحبت کلی دربارهٔ شیفت‌های تعطیلات بدون این عبارت عمومی است."
        ),
        "text": "لطفاً لیست آن‌کال نوروز را فقط برای سرپرست‌ها بفرست و در کانال عمومی پین نکن.",
        "notes": "Confidential policy phrase present",
    },
    {
        "id": "fa-guidance-fa-org-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "عبارت «لیست آن‌کال نوروز» محرمانه است چون شامل برنامهٔ حضور افراد می‌شود. "
            "صحبت کلی دربارهٔ شیفت‌های تعطیلات بدون این عبارت عمومی است."
        ),
        "text": "چطور شیفت‌های تعطیلات طولانی را بین تیم‌ها عادلانه تقسیم کنیم؟",
        "notes": "Holiday staffing topic only",
    },
    # --- Harder: long Persian prose with buried policy phrase ---
    {
        "id": "fa-guidance-fa-buried-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "adversarial"],
        "guidance_prompt": (
            "اسم رمز «اوریون-۹» محدود است. پیام‌های طولانی که فقط در میانه نام را می‌آورند هم باید محدود شوند."
        ),
        "text": (
            "سلام، امیدوارم ریویو اسلایدها خوب پیش رفته باشد. چند نکتهٔ ویرایشی دربارهٔ لحن داشتم. "
            "ضمناً وضعیت اوریون-۹ را فقط در کانال عملیات به‌روز کنید و در رشتهٔ عمومی تکرار نکنید. "
            "بقیهٔ بخش‌های آموزشی را می‌توان فردا منتشر کرد."
        ),
        "notes": "Buried codename in long FA email",
    },
    {
        "id": "fa-guidance-fa-buried-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy", "adversarial"],
        "guidance_prompt": (
            "اسم رمز «اوریون-۹» محدود است. پیام‌های طولانی که فقط در میانه نام را می‌آورند هم باید محدود شوند."
        ),
        "text": (
            "سلام، امیدوارم ریویو اسلایدها خوب پیش رفته باشد. چند نکتهٔ ویرایشی دربارهٔ لحن داشتم. "
            "لطفاً وضعیت پروژه‌های داخلی را فقط در کانال عملیات به‌روز کنید. "
            "بقیهٔ بخش‌های آموزشی را می‌توان فردا منتشر کرد."
        ),
        "notes": "Same long structure without codename",
    },
    # --- Combined policy: multiple phrases, one present ---
    {
        "id": "fa-guidance-fa-multi-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy"],
        "guidance_prompt": (
            "این موارد محدودند: «رشته نقره‌ای»، «شاهین کویر»، «پرنده آبی». "
            "بحث معماری service mesh یا گسترش منطقه‌ای بدون این نام‌ها عمومی است."
        ),
        "text": "برای FAQ داخلی مهاجرت mesh از نام برنامه استفاده نکنید؛ فعلاً فقط رشته نقره‌ای در کانال محدود مجاز است.",
        "notes": "One of three policy names present",
    },
    {
        "id": "fa-guidance-fa-multi-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "این موارد محدودند: «رشته نقره‌ای»، «شاهین کویر»، «پرنده آبی». "
            "بحث معماری service mesh یا گسترش منطقه‌ای بدون این نام‌ها عمومی است."
        ),
        "text": "برای مهاجرت تدریجی به service mesh چه FAQ داخلی بدون نام برنامه باید منتشر شود؟",
        "notes": "Mesh FAQ without any listed name",
    },
    # --- Base secret + Persian policy together ---
    {
        "id": "fa-guidance-fa-mixed-secret-hit-01",
        "lang": "fa",
        "gold_category": "restricted",
        "tags": ["guidance", "value_present", "hard", "fa_policy", "secret"],
        "guidance_prompt": (
            "نام فروشنده «هلیو» دادهٔ فروشندهٔ محدود است. هر رمز عبور یا کلید همراه آن هم محدود است."
        ),
        "text": "پشتیبانی هلیو گفت موقتاً از رمز Temp!Helio2024 روی پورتال استفاده کنید؛ بعداً عوض شود.",
        "notes": "Policy vendor + password both present",
    },
    {
        "id": "fa-guidance-fa-mixed-secret-miss-01",
        "lang": "fa",
        "gold_category": "public",
        "tags": ["guidance", "topic_only", "hard", "fa_policy"],
        "guidance_prompt": (
            "نام فروشنده «هلیو» دادهٔ فروشندهٔ محدود است. هر رمز عبور یا کلید همراه آن هم محدود است."
        ),
        "text": "چطور رمزهای موقت پورتال فروشندگان را بعد از اتمام پشتیبانی rotate کنیم؟",
        "notes": "Vendor password process without Helio name or password",
    },
]


def main() -> None:
    existing: dict[str, dict] = {}
    if CORPUS.is_file():
        for line in CORPUS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                existing[r["id"]] = r

    added = 0
    for r in ROWS:
        if r["id"] in existing:
            existing[r["id"]] = r  # refresh if re-run
            continue
        existing[r["id"]] = r
        added += 1

    rows = sorted(existing.values(), key=lambda x: x["id"])
    CORPUS.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    fa_full = [
        r
        for r in rows
        if r.get("guidance_prompt")
        and r.get("lang") == "fa"
        and any("\u0600" <= c <= "\u06FF" for c in r["guidance_prompt"])
    ]
    print(f"total={len(rows)} newly_added={added} fa_full_persian_guidance={len(fa_full)}")


if __name__ == "__main__":
    main()
