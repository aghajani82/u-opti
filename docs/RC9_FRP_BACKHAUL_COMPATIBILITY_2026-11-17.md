# RC9 — بررسی سازگاری FRP و Backhaul با نصب یک‌گزینه‌ای ایران/خارج

**تاریخ:** 2026-11-17  
**مخزن:** `aghajani82/u-opti`، برنچ `trial/unified-smite-install`، PR #202 (Draft)  
**مبنای بازرسی:** `ffd163acd3ee76fc035e82cb29c334ae9800f989` و سورس دقیق Smite RC9 `e7f76185e9a7da51d7069d5d0a829dc192cc1e06`  
**دامنه:** فقط آماده‌سنجی سازگاری موتورهای موجود پس از گزینه‌های ۱ (ایران) و ۲ (خارج). بدون قابلیت، منو، Workflow یا PR جدید. بدون تغییر `main`، سرویس زنده، سانایی یا تانل‌های موجود.

## 1) شواهد ارسال‌شده از هر دو میزبان آزمایشی

روی `iran` و `kharej` دستور زیر اجرا و خروجی آن ارائه شد:

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-managed-frp-control.py review --rc9-wss-plan
```

| بررسی | ایران | خارج |
| --- | --- | --- |
| نقش | `ROLE=IR` | `ROLE=KH` |
| منبع | `RC9_SIGNED_SOURCE=EXACT_LOCAL_STATE` | همان |
| ایمیج | `RC9_IMAGE=PINNED_REFERENCE_AND_LOCAL_IMAGE_ID` | همان |
| runtime نود | `HEALTHY_SIGNED_POLICY_LOCAL_ONLY` | همان |
| باینری‌های FRP | `BUNDLED_0_71_0` | همان |
| تفاوت Compose برای WSS | `EXACT_ONE_ENV_ONLY` | همان |
| سرویس‌های تحت تأثیر **در طرح** | `PANEL_AND_NODE` | `NODE_ONLY` |
| ثبت موتور FRP | `NO` | `NO` |
| تأیید Nginx Edge | `NOT_VERIFIED` | همان |
| WSS فعال | `NOT_ENABLED` | همان |
| Owner FRPS | `NOT_VERIFIED` | همان |
| replay با HMAC | `NOT_QUERIED` | همان |
| مجوز تغییر میزبان | `INSTALL_ALLOWED=NO` | همان |
| بازسازی Node / تغییر پورت‌ها | `NO` / `NO` | همان |

**تفسیر دقیق:** `EXACT_LOCAL_STATE` و تطابق مرجع/شناسه محلی ایمیج، تأیید مستقل امضای باینری، ثبت موتور، اتصال دوطرفهٔ تانل یا پایداری پس از راه‌اندازی مجدد نیست. این بررسی هیچ تغییری روی میزبان ایجاد نکرده است. وضعیت اتصال قبلی Node به Panel، در صورت تأیید جداگانه، دلیل اتصال FRP/Backhaul نیست.

## 2) تطبیق با سورس واقعی RC9

- [Dockerfile نود RC9](https://github.com/aghajani82/Smite/blob/e7f76185e9a7da51d7069d5d0a829dc192cc1e06/node/Dockerfile): هر دو `frpc` و `frps` نسخه `v0.71.0` و `backhaul` نسخه `v0.7.2` در build به مسیرهای ثابت `/usr/local/bin/` کپی می‌شوند؛ دریافت آرشیوهای آن‌ها با SHA256 pin شده است.
- [Engine inventory دقیق RC9](https://github.com/aghajani82/Smite/blob/e7f76185e9a7da51d7069d5d0a829dc192cc1e06/node/app/engine_inventory.py): وجود باینری به‌تنهایی کافی نیست. `managed` باید یک manifest قابل‌اعتماد، `sha256` معتبر، و برای FRP هر دو هش `frpc/frps` داشته باشد تا `ready` شود.
- [RC9 FRP review](../modules/smite-managed-frp-control.py): پیش‌شرط‌های Node امضاشدهٔ در حال اجرا، Compose owner و تغییر یک‌کلید WSS را **صرفاً خواندنی** بررسی می‌کند؛ `install/rollback` روی میزبان واقعی همچنان ممنوع است.
- [RC7 bundled FRP enrollment](../modules/smite-rc7-frp-enrollment.py): این مسیر به journal امضاشدهٔ WSS **نسخه RC7** وابسته است و نباید بدون تطبیق مستقل و بازبینی برای RC9 استفاده شود.
- [Independent Backhaul control](../modules/smite-managed-backhaul-control.py): بازرسی `status/review` فقط وضعیت محلی را نشان می‌دهد؛ مسیر نصب/rollback واقعی در این کنترلر غیرفعال است. مسیر RC7 `verify-rc7-bundle` **گواه سازگاری اجرایی RC9 نیست**.
- [Managed FRP transaction](../modules/smite-managed-frp-transaction.py) و [Backhaul transaction](../modules/smite-managed-backhaul-transaction.py) تنها در fixture آزمایشگاهی ایزوله و با قفل مشترک Compose/manifest می‌نویسند؛ این‌ها مجوز اجرای مستقیم در روت سرور واقعی نیستند.

### نتیجهٔ سازگاری

**سازگاری ساختاری / بسته‌بندی: PASS (از روی سورس و خروجی‌های حاضر)** — موتورهای مورد نظر در RC9 پیش‌بینی شده‌اند، با schema موجود Node قابل ثبت‌اند و مستقل از هم نگهداری می‌شوند.  
**سازگاری عملی مشترک HTTPS/443 و بازیابی: NOT PROVEN** — مسیر Nginx/443، هویت و replay امضاشده، اتصال FRPS Owner/FRPC Child، ایزولاسیون Backhaul/XHTTP، resume و rollback واقعی هنوز گواه ندارند.  
**مجوز نصب موتور یا ساخت تانل: HOLD** — از خروجی فعلی نمی‌توان فرمان فعال‌سازی ایمن صادر کرد. این HOLD نقص در اصل حضور باینری‌ها نیست؛ نبود زنجیرهٔ تأیید و جبران تغییر میزبان RC9 است.

## 3) بررسی‌های **صرفاً خواندنی** پیشنهادی برای دو میزبان

بدون تغییر فایل‌ها، بدون `docker compose up`، بدون restart/recreate و بدون نصب میزبان:

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-managed-backhaul-control.py review
docker exec smite-node sha256sum /usr/local/bin/frpc /usr/local/bin/frps /usr/local/bin/backhaul
```

خروجی Backhaul هنوز از این دو میزبان دریافت نشده؛ **فعلاً دربارهٔ وضعیت نصب Backhaul ادعا نمی‌کنیم**. هش‌های چاپ‌شده فقط اثرانگشت باینری مشاهده‌شده‌اند و به‌تنهایی اعتبار release یا موتور نصب‌شده را اثبات نمی‌کنند. اگر دستور خواندنی خطا داد، علت باید قبل از نصب تحلیل شود. از `verify-rc7-bundle` برای RC9 استفاده نشود.

## 4) ترتیب دقیق بستن Gateهای موجود، بدون اضافه‌کردن قابلیت

1. **گیت مبنا:** بررسی ثبت معتبر source/digest هر دو ایمیج، سلامت Node/Panel و signed HMAC replay بر روی هر دو میزبان؛ ثبت اصل وضعیت identity، manifest و سرویس‌ها پیش از تغییر.
2. **گیت FRP/443:** بازبینی Nginx Edge و تعارض مسیرهای HTTPS/443؛ تطبیق همان WSS یک‌کلید با Compose owner واقعی؛ برنامهٔ دقیق rollback برای IR (Panel+Node) و KH (Node) بدون حذف identity/FRP/Backhaul/Sanaei. `RC9_WSS_RUNTIME_APPLY` تا تأیید برنامه و آزمایش ایزوله HOLD بماند.
3. **گیت ثبت FRP:** استفادهٔ بازبینی‌شده از منطق موجود باینری‌های bundled، ثبت اتمیک dual-digest با journal خصوصی و قفل مشترک؛ بررسی signed inventory و FRPS owner در ایران، child در خارج و تونل واقعی، بدون افزودن پورت عمومی.
4. **گیت Backhaul مستقل:** صرفاً پس از اثبات حفظ FRP، ثبت اتمیک و مستقل Backhaul v0.7.2 در همان inventory، با رعایت journal قبلی FRP؛ بررسی XHTTP و اشتراک امن HTTPS/443؛ عدم دست‌کاری تونل‌های FRP موجود.
5. **گیت rollback/دو میزبان:** اثبات resume و rollback در شکست تک‌مرحله‌ای/قطع عملیات، سلامت `node-ir` و `node-kh`، عدم تغییر دیتابیس سانایی، حفظ identity، و اتصال واقعی مجدد. فقط بعد از مدارک witnessed و مجوز فعال‌سازی مشخص، اجرای واقعی بررسی شود.

**حد ایمنی قطعی:** تا بستن این گیت‌ها به ترتیب، `main`، سرورهای عملیاتی، Grandoptical، Nodeهای سالم، FRP فعلی و Backhaul دست‌نخورده بمانند. هیچ اسکریپت قدیمی RC7 با تغییر سطحی نام RC9 قابل اجرای خودکار نیست.

## 5) وضعیت CI در زمان بررسی

بر روی SHA `ffd163ac`، ۹ workflow وابسته به همین commit در GitHub Actions با نتیجه `success` ثبت شده‌اند (شامل CI و Foreign installation client). این‌ها **تست‌های repository/fixture** هستند؛ نتیجهٔ PASS معادل witnessed live tunnel یا مجوز نصب نیست.

**گام فعلی:** جمع‌آوری دو خروجی خواندنی Backhaul و نسخه‌های باینری از ایران/خارج، سپس رفع فقط نقص‌های مستند در کنترل‌های موجود و آزمایش آفلاین؛ افزودن feature/Workflow/PR جدید ممنوع.
