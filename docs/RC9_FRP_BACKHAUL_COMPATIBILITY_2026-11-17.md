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

**نتیجهٔ این دستورات از هر دو میزبان در 2026-11-17 دریافت شده و در بخش ۶ ثبت شده است.** هش‌های چاپ‌شده فقط اثرانگشت باینری مشاهده‌شده‌اند و به‌تنهایی اعتبار release یا موتور نصب‌شده را اثبات نمی‌کنند. از `verify-rc7-bundle` برای RC9 استفاده نشود.

## 4) ترتیب دقیق بستن Gateهای موجود، بدون اضافه‌کردن قابلیت

1. **گیت مبنا:** بررسی ثبت معتبر source/digest هر دو ایمیج، سلامت Node/Panel و signed HMAC replay بر روی هر دو میزبان؛ ثبت اصل وضعیت identity، manifest و سرویس‌ها پیش از تغییر.
2. **گیت FRP/443:** بازبینی Nginx Edge و تعارض مسیرهای HTTPS/443؛ تطبیق همان WSS یک‌کلید با Compose owner واقعی؛ برنامهٔ دقیق rollback برای IR (Panel+Node) و KH (Node) بدون حذف identity/FRP/Backhaul/Sanaei. `RC9_WSS_RUNTIME_APPLY` تا تأیید برنامه و آزمایش ایزوله HOLD بماند.
3. **گیت ثبت FRP:** استفادهٔ بازبینی‌شده از منطق موجود باینری‌های bundled، ثبت اتمیک dual-digest با journal خصوصی و قفل مشترک؛ بررسی signed inventory و FRPS owner در ایران، child در خارج و تونل واقعی، بدون افزودن پورت عمومی.
4. **گیت Backhaul مستقل:** صرفاً پس از اثبات حفظ FRP، ثبت اتمیک و مستقل Backhaul v0.7.2 در همان inventory، با رعایت journal قبلی FRP؛ بررسی XHTTP و اشتراک امن HTTPS/443؛ عدم دست‌کاری تونل‌های FRP موجود.
5. **گیت rollback/دو میزبان:** اثبات resume و rollback در شکست تک‌مرحله‌ای/قطع عملیات، سلامت `node-ir` و `node-kh`، عدم تغییر دیتابیس سانایی، حفظ identity، و اتصال واقعی مجدد. فقط بعد از مدارک witnessed و مجوز فعال‌سازی مشخص، اجرای واقعی بررسی شود.

**حد ایمنی قطعی:** تا بستن این گیت‌ها به ترتیب، `main`، سرورهای عملیاتی، Grandoptical، Nodeهای سالم، FRP فعلی و Backhaul دست‌نخورده بمانند. هیچ اسکریپت قدیمی RC7 با تغییر سطحی نام RC9 قابل اجرای خودکار نیست.

## 5) وضعیت CI در زمان بررسی

بر روی SHA `ffd163ac`، ۹ workflow وابسته به همین commit در GitHub Actions با نتیجه `success` ثبت شده‌اند (شامل CI و Foreign installation client). این‌ها **تست‌های repository/fixture** هستند؛ نتیجهٔ PASS معادل witnessed live tunnel یا مجوز نصب نیست.

**گام فعلی:** شواهد خواندنی Backhaul و SHA256 باینری‌ها از هر دو میزبان دریافت شد؛ گام بعد، بستن گیت WSS/Nginx/rollback با کنترل‌های موجود و تست آفلاین است؛ افزودن feature/Workflow/PR جدید ممنوع.


## 6) شواهد تازهٔ واقعی دو میزبان — 2026-11-17

**منشأ:** خروجی دستورهای خواندنی که اپراتور از `root@iran` و `root@kharej` ارائه کرد. این‌ها **شواهد مشاهده‌ای** هستند، نه امضای انتشار یا گزارش اتصال تونل.

| مشاهده | ایران | خارج |
| --- | --- | --- |
| `smite-managed-backhaul-control.py review` | `ROLE=IR` | `ROLE=KH` |
| `STATE / REASON` | `NOT_INSTALLED / NO_ENROLLMENT` | `NOT_INSTALLED / NO_ENROLLMENT` |
| `INSTALL_ALLOWED` | `NO` | `NO` |
| `HOST_DOCKER_ACTIONS` | `NONE` | `NONE` |
| `FRP_DEPENDENCY` | `NONE` | `NONE` |
| `NEXT` | `CI_ONLY_UNTIL_HOST_ROLLBACK_APPROVAL` | همان |

هش‌های خوانده‌شده با `docker exec smite-node sha256sum` در **هر دو** میزبان، بدون اختلاف:

```text
f79fff8de3089ec711ff8bdd4b73e00dfe491a1c3d754983c8b0f8d58c21b068  /usr/local/bin/frpc
b95dee2bf29a021c562565cdf2116376b9fa7590361bd36ef57041a04d0e6654  /usr/local/bin/frps
7f1b1439d7fe1d15ae0b376e15614fe13d8a12f6e07a90263e310ea2a9d601fb  /usr/local/bin/backhaul
```

- **Backhaul:** هش اجراپذیر مشاهده‌شده دقیقاً با `OFFICIAL_BINARY_SHA256["amd64"]` در [بستهٔ موجود پروژه](../modules/smite-managed-backhaul.py) مطابقت دارد و با `v0.7.2` رسمی ثبت‌شده مرتبط است. این انطباق فقط باینری است، نه مجوز ثبت یا اجرای موتور.
- **FRP:** هر دو نقش `frpc` و `frps` در دو میزبان هش یکسان دارند؛ `RC9_FRP_VERSION` پیش‌تر در بررسی WSS نسخهٔ `0.71.0` مشاهده شده است. این دو هش هنوز در این گزارش در برابر **هش مستقلِ باینری استخراج‌شده از آرشیو رسمی** تطبیق نشده‌اند؛ صرف همسانی، امضای رمزنگاری‌شدهٔ انتشار را جایگزین نمی‌کند. از پین‌های باینری نسخه RC2 به‌عنوان مرجع RC9 استفاده نشود.
- **سازگاری:** `NOT_INSTALLED` دقیقاً به نبود ثبت inventory در میزبان اشاره دارد؛ عدم حضور executable را نتیجه نمی‌دهد. بنابراین نصب مجدد Node یا بارگیری دوبارهٔ Backhaul بر اساس این خروجی‌ها توجیه ندارد.
- **تست بازگشت:** تست موجود `tests/test-smite-managed-backhaul-control.py` برای هر دو نقش `IR` و `KH` تأکید می‌کند که نبود enrollment نباید به `installed` یا مجوز اجرای واقعی ارتقا یابد؛ هیچ API یا ویژگی تازه‌ای اضافه نشده است.

### کار باقیمانده (در همان scope)

1. ابتدا برنامهٔ rollback/restore و بررسی Nginx/HTTPS 443 و تأیید signed replay برای همین RC9؛ **بدون** اجرای `smite-rc7-wss-runtime.py` روی Node RC9.
2. سپس تطبیق و تست آفلاین stage-owned enrollment برای FRP bundled، گواه Owner/Child و WSS ایزوله از Panel، Backhaul و Sanaei.
3. بعد از آن بررسی مستقل Backhaul با استفاده از journal/lock موجود و درستی اتصال و rollback، **بدون** خراب‌کردن FRP.
4. فقط پس از وجود مدارک ریشهٔ واقعیِ دو سرور، دریافت مجوز نصب و تکمیل checks، بازبینی نهایی PR #202 و merge؛ `main` فعلاً تغییر نمی‌کند.

**وضعیت امنیتی نهایی این بازبینی: `FRP_INSTALL=HOLD`، `BACKHAUL_INSTALL=HOLD`، `LIVE_CHANGES=NONE`.**

## 7) RC9 Nginx/443 listener evidence — 2026-11-17

Operator-provided **read-only** output on fresh trial hosts `iran` and `kharej`:

| Evidence | Iran | Foreign |
| --- | --- | --- |
| `nginx -t` | syntax OK; test successful | syntax OK; test successful |
| Public TCP 443 owner | Nginx on `0.0.0.0:443` and `[::]:443` | Nginx on `0.0.0.0:443` and `[::]:443` |
| Configuration warnings | None in excerpt | non-fatal deprecated `listen ... http2` at `/etc/nginx/sites-enabled/3xui-kharej.grandoptical.ir:13` |
| FRP WSS `/~!frp` route | NOT_OBSERVED | NOT_OBSERVED |
| IR stream SNI/source-IP map | NOT_QUERIED | N/A |
| IR loopback `8443/8444` backends and `7000` owner | NOT_QUERIED | N/A |
| FRP/Backhaul host activation approval | NO | NO |

**Interpretation:** Nginx accepts the current configuration and owns the socket; this does not establish FRP WSS path, SNI allowlist, certificate-valid request routing, connected tunnel, Node replay or rollback. The existing `3xui-` site warning is syntactic compatibility feedback, not a failed Nginx test. Do not edit live Sanaei/3xUI site solely to silence the warning.

**Important legacy boundary:** `modules/smite-rc2-frp-wss-edge-plan.py` is restricted to the legacy `ir` hostname and RC2-specific edge topology (and uses a legacy default domain); the current Iran host reports `iran`. `modules/smite-rc7-wss-preflight.py` and `modules/smite-rc7-wss-edge.py` are RC7-only, with explicit pinned RC7 role/version and signed runtime admission. Reusing their *guarded read-only primitives* from the RC9 reviewer is legitimate where separately checked; running their old RC7 mutating CLI against RC9 is **not** authorized. The current RC9 `review --rc9-wss-plan` correctly reports `RC9_WSS_NGINX_EDGE=NOT_VERIFIED`, `RC9_WSS_SIGNED_FRP=NOT_ENROLLED` and `RC9_WSS_RUNTIME_APPLY=HOLD_RECREATE_AND_ROLLBACK_NOT_APPROVED` despite a valid one-key Compose proposal. This safety distinction is asserted in the existing tests.

### Next redacted, safe local topology inspection (no writes)

Run separately as root on Iran and Foreign; keep the output limited to **directive names** and bound sockets rather than sharing full `nginx -T` configuration, credentials or certificates:

```bash
echo '=== TLS/SNI and WSS routing declarations (redacted) ==='
nginx -T 2>/dev/null |
  grep -E '^[[:space:]]*(listen[[:space:]]+.*(443|8443|8444)|server_name[[:space:]]+|location[[:space:]]+.*(/~!frp|/smite-node)|ssl_preread[[:space:]]+on;)' |
  head -n 80
echo '=== Loopback/FRP control listeners ==='
ss -lnt '( sport = :7000 or sport = :8443 or sport = :8444 )'
```

This is route discovery only; `nginx -T` itself **prints the full configuration**, so never share its unfiltered output. No `nginx reload`, `docker compose up`, old RC7 `apply`, FRPS start or any new port opening.

**CI:** On preceding commit `2cececa5`, all nine workflows completed `success` (repository/fixture evidence). All later commits require fresh CI on their own exact SHA. This does not grant any deployment approval.

**Next gate:** matched RC9 HTTPS/443 edge topology and no-proxy WSS plan with strict role/owner/rollback, then FRP owner/child, then independent Backhaul; no changes to `main` until witnessed two-host recovery and permission.

## 8) 2026-11-17: dynamic domain correction and actual IR/KH routes

The operator explicitly requires **dynamic Panel DNS names and hostnames**, not fixed `ir`, `iran`, `01` or `04` labels. A hostname such as `iran` is not the Panel domain. RC9 derives `SMITE_PANEL_DOMAIN` from the exact per-host `/etc/u-opti/smite/state.env` and checks it against the Node `PANEL_ADDRESS=<domain>:443`; never infer one from a hardcoded legacy RC2 source constant or a particular current server number. The RC2-only hostname/domain assertions remain untouched and are **not** runnable activation tools for RC9.

### Read-only observed Nginx topology

| Host | `nginx -T` filtered observations | Loopback/internal `ss -lnt` |
| --- | --- | --- |
| IR, host `iran` | Public stream `listen 443`, `listen [::]:443`, `ssl_preread on`; TLS Panel backend `listen 127.0.0.1:8443 ssl`; `server_name 04.grandoptical.ir` | `127.0.0.1:8443` listening; neither `7000` nor `8444` listening |
| KH, host `kharej` | Shared TLS `listen 443 ssl http2` on IPv4 and IPv6; `server_name kharej.grandoptical.ir`; existing `location ^~ /smite-node/<id>/` | No `7000`, `8443` or `8444` listener reported |

The private KH Node route ID is not reproduced here. Full `nginx -T` was not shared. The previous independent Nginx syntax PASS remains valid, with only the nonfatal KH deprecated `listen ... http2` warning.

**Live classification:** `IR_PANEL_STREAM_443=OBSERVED`, `IR_PANEL_TLS_BACKEND_8443=OBSERVED`, `KH_NODE_CONTROL_443_LOCATION=OBSERVED`. `IR_WSS_EDGE_8444=NOT_PRESENT`, `FRPS_OWNER_7000=NOT_LISTENING`, `SIGNED_FRPC_CHILD=NOT_PROVEN`, `FRP_ENGINE_ENROLLED=NO`, `BACKHAUL_ENGINE_ENROLLED=NO`. This is a consistent **pre-enrollment** state, not proof that the existing Panel or Node install is defective.

**Actual code defect corrected within the existing RC9 review:** the prior WSS scope regex `[a-z0-9.-]{4,253}` accidentally admitted malformed DNS labels (`bad..domain`, leading/trailing label hyphens). The RC9 plan now uses the existing strict DNS-label validator from the original reusable RC7 read-only primitive, against the **dynamic signed state domain**; this is validation repair, *not* reintroducing an RC7 version/domain pin or a new feature. Existing test now checks several valid domains (including `01.grandoptical.ir` and a different suffix), malformed domain HOLD **before any Docker calls**, and preservation of `RC9_WSS_NGINX_EDGE=NOT_VERIFIED` even for a valid Compose candidate.

**Still pending:** a separately reviewed RC9 live WSS/FRP/Backhaul host executor with exact signed inventory, shared 443 SNI/ACL proof, unchanged Sanaei/Node identity and stage-local rollback before running any tunnel. Never use legacy RC2/RC7 write actions on these RC9 servers. No host changes or additional public ports.
