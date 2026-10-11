# فقط برای تو ♡

ربات تلگرام + Telegram Mini App برای ثبت خاطرات، ویس، عکس، نامه و روزشمار رابطه.

## ساختار پروژه

```
.
├── bot.py              # ربات + API + زمان‌بندی + دیتابیس
├── webapp/
│   └── index.html      # Mini App کامل
├── requirements.txt
├── Procfile
├── runtime.txt
└── README.md
```

## متغیرهای محیطی (Railway / .env)

| متغیر | توضیح |
|---|---|
| `BOT_TOKEN` | توکن ربات از BotFather |
| `ADMIN_ID` | عددی، شناسه عددی مدیر |
| `ALLOWED_USER_ID` | عددی، شناسه عددی کاربر مجاز |
| `WEBAPP_URL` | آدرس HTTPS مینی‌اپ (مثلاً `https://your-app.railway.app`) |
| `GEMINI_API_KEY` | اختیاری، برای تولید پیام‌های عاشقانه با Gemini |
| `GEMINI_MODEL` | اختیاری، پیش‌فرض `gemini-1.5-flash` |
| `DB_PATH` | مسیر دیتابیس، پیش‌فرض `/app/data/app.db` |
| `UPLOAD_DIR` | مسیر فایل‌ها، پیش‌فرض `/app/data/uploads` |
| `TIMEZONE` | پیش‌فرض `Asia/Tehran` |
| `PORT` | پورت وب، پیش‌فرض `8080` |

## استقرار روی Railway

### ۱) ایجاد پروژه
- در Railway یک پروژه جدید بساز و ریپازیتوری GitHub را متصل کن.
- یک سرویس از قالب **Python** ایجاد کن.

### ۲) افزودن Volume (برای دیتابیس و فایل‌ها)
- در سرویس، تب **Volumes** را باز کن.
- یک Volume جدید بساز و Mount Path را روی `/app/data` تنظیم کن.
- این کار باعث می‌شود دیتابیس و فایل‌های آپلودشده پایدار بمانند.

### ۳) تنظیم متغیرها
در تب **Variables** این متغیرها را وارد کن:
- `BOT_TOKEN`
- `ADMIN_ID`
- `ALLOWED_USER_ID`
- `WEBAPP_URL` (بعد از گرفتن دامنه در مرحله بعد)
- `GEMINI_API_KEY` (اختیاری)
- `TIMEZONE=Asia/Tehran`

### ۴) گرفتن دامنه HTTPS
- در تب **Settings** سرویس، بخش **Networking** → **Generate Domain** را بزن.
- دامنه‌ای مثل `https://your-app.railway.app` می‌گیری.
- این دامنه را در `WEBAPP_URL` قرار بده و سرویس را Deploy Again کن.

### ۵) تنظیم Mini App در BotFather
1. در تلگرام `/newbot` را اجرا کن (یا از bot موجود استفاده کن).
2. `/mybots` → ربات خودت را انتخاب کن.
3. **Bot Settings** → **Menu Button** → **Configure menu button**.
4. آدرس مینی‌اپ (همان `WEBAPP_URL`) را وارد کن.
5. متن دکمه را مثلاً `♡ باز کن` بگذار.

### ۶) فعال‌کردن Mini App برای ربات
در BotFather:
- `/mybots` → ربات → **Bot Settings** → **Menu Button** → **Edit menu button URL**
- آدرس HTTPS دامنه Railway را وارد کن.

## اجرای محلی

```bash
python -m venv venv
source venv/bin/activate   # در ویندوز: venv\Scripts\activate
pip install -r requirements.txt

export BOT_TOKEN="..."
export ADMIN_ID="..."
export ALLOWED_USER_ID="..."
export WEBAPP_URL="http://localhost:8080"
export DB_PATH="./data/app.db"
export UPLOAD_DIR="./data/uploads"

python bot.py
```

سپس در مرورگر `http://localhost:8080` را باز کن (برای تست Mini App در تلگرام، باید روی HTTPS باشد؛ از ngrok یا Cloudflare Tunnel برای تونل HTTPS استفاده کن).

## تست

- در ربات `/start` را بزن → شرایط حریم خصوصی نمایش داده می‌شود.
- پس از پذیرش، منوی اصلی باز می‌شود.
- از دکمه «🖥 باز کردن مینی‌اپ» وارد Mini App شو.
- ثبت خاطره، ضبط ویس، افزودن عکس، مشاهده نامه‌ها و مناسبت‌ها را تست کن.

## نکات امنیتی

- توکن ربات و کلیدها هرگز در کد یا ریپازیتوری قرار نمی‌گیرند.
- تمام درخواست‌های API با روش رسمی Telegram Web Apps (`initData` + HMAC-SHA256) احراز هویت می‌شوند.
- فایل‌های خصوصی فقط از مسیر `/api/files/{kind}/{id}` و با احراز هویت قابل دسترسی‌اند.
- مسیر فایل‌ها با `is_safe_path` اعتبارسنجی می‌شود تا از directory traversal جلوگیری شود.

## روز دختر

- به‌صورت پیش‌فرض از ۵ جمادی‌الثانی (ولادت حضرت معصومه س) با کتابخانه `hijri-converter` برای هر سال شمسی محاسبه می‌شود.
- مدیر می‌تواند از تنظیمات، تاریخ دقیق شمسی را دستی وارد کند.

## پیام‌های زمان‌بندی‌شده

- ساعت ۶:۰۰ صبح و ۰۰:۰۰ شب به وقت `Asia/Tehran`.
- با ثبت در جدول `scheduled_messages` از ارسال تکراری در صورت ری‌استارت جلوگیری می‌شود.
- در صورت خطای Gemini، از پیام‌های آماده استفاده می‌شود و ربات متوقف نمی‌شود.