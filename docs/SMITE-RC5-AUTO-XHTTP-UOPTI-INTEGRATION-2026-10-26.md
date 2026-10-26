# U-OPTI × Smite — Auto XHTTP route integration and release gates (2026-10-26)

> **Closeout update — 2026-10-26:** The checkpoint below is historical and has been superseded by [U-OPTI PR #48](https://github.com/aghajani82/u-opti/pull/48) at `546ed5198aa30aae24b597a37ac6b55fa8825b84` and [Smite PR #32](https://github.com/aghajani82/Smite/pull/32) at `da1c08896508a5c9b3d7601d2943575b90f5c223`. The scoped U-OPTI broker, separate per-child root grant, KH read-only Sanaei inventory mount, and Panel wizard-to-signed-route flow are implemented on those Draft PRs. Current-head CI passed: U-OPTI 6/6 and Smite 12/12 triggered workflows. This validates source and isolated CI only.
>
> **Remaining acceptance gate:** a disposable clean Ubuntu IR/KH install, a real third KH XHTTP inbound, automatic route registration, real TLS/443 client traffic, reboot/reconnect, and failure/rollback checks. No two-host clean-install test has run. `main`, released tags, existing test hosts and their working routes, and Grandoptical remain untouched.
>
> The details below preserve the earlier design checkpoint; statements that work was “unimplemented” refer to that earlier date, not the current Draft PR source.

**Status (2026-10-26):** signed Node-to-local-broker forwarding, per-child root approval, KH read-only Sanaei inventory, existing FRP wizard route submission and clean-RC broker bootstrap are implemented on the development branches; GitHub CI passed on current heads. This remains source-only: no real clean dual-VPS install or third-inbound client test has been performed. The root grant CLI reports operator-asserted evidence and does not cryptographically re-fetch remote proofs. No live install, update, restart, merge to `main`, release version bump, or change to existing working inbounds is authorized.

**Related Smite handoff:** [FRPS multiport closeout](https://github.com/aghajani82/Smite/blob/feature/smite-rc2-frp-singleton-multiport-20261025/docs/FRP-SINGLETON-MULTIPORT-FIELD-CLOSEOUT-2026-10-26.md). Smite feature HEAD has an offline route planner ([PR #27](https://github.com/aghajani82/Smite/pull/27)), signed KH inbound inventory ([PR #26](https://github.com/aghajani82/Smite/pull/26)) and **root-only local Nginx transaction helper** ([PR #29](https://github.com/aghajani82/Smite/pull/29)), which is **not wired to an authorized Agent/Panel flow** and not yet part of a signed release.

## Decision: yes, U-OPTI needs a reviewed update — but do NOT update the live IR/KH hosts yet

**Division of ownership:**

- **U-OPTI (IR host):** IR/KH role bootstrap, approved TLS/443 gateway and effective IR Nginx backend; scoped Nginx include/bridge installation, host-only permission boundaries, safety preflight, backup/journal/recovery, service lifecycle, installer/update/rollback.
- **Smite Panel:** beginner-friendly choice of independent engine (FRP, Backhaul, etc.), IR/KH Node pair, verified KH Sanaei inbound, unique FRP lease/shared child and operator status. No unrestricted filesystem write privileges.
- **Signed Node KH:** read-only, explicitly opted-in local Sanaei XHTTP inventory. Only port/path/transport/enable/listen are exposed, not UUIDs, client records, raw database, or token.
- **Signed Node IR ↔ local host broker:** narrow authorized request to add/remove only the specific verified child route. Enforce tunnel ID, KH node binding, port+path, replay/idempotency and signed owner/lease proof; never execute a user-supplied shell script, arbitrary command or include file. The broker/IPC contract remains unimplemented.
- **U-OPTI and Smite must not both write the same route file.** Route owner must be explicit and exclusive.

## Existing working baseline — preserve byte-for-byte

Operator field tests confirmed two live clients:

| IR FRPS data port | KH Sanaei XHTTP path | Observed host route owner |
|---:|---|---|
| 45121 | `/45121/www` | `/etc/nginx/u-opti-smite-frp-xhttp.conf` |
| 49328 | `/49328/sso` | `/etc/nginx/u-opti-smite-frp-xhttp.conf` |

One FRPS remains at `127.0.0.1:7000`, both data ports loopback, two KH FRPC, real client PASS after `nginx -t` and a controlled reload. **Neither route is to be moved, re-rendered, deleted, auto-imported or reapplied as part of this integration.** The existing U-OPTI automatic route timer was reported disabled during the RC2 trial; re-check this read-only before any migration. It must not begin competing with the new owner.

## Crucial compatibility finding

The existing U-OPTI `modules/smite-frp-xhttp.sh` manages a **whole-file rendered** `/etc/nginx/u-opti-smite-frp-xhttp.conf` from Node tunnel state plus `/etc/u-opti/smite/frp-xhttp-paths.json`. The Smite new host helper uses a **new file per inbound** under `/etc/nginx/smite-xhttp-routes/<port>.conf`, requiring an independently preinstalled bridge `/etc/nginx/smite-xhttp-bridge.conf` containing exactly `include /etc/nginx/smite-xhttp-routes/*.conf;`.

That separation is intentional but **not enough**: U-OPTI needs to verify the bridge is included **inside the correct IR Panel TLS backend server**. On the current U-OPTI gateway public 443 may be stream-routed to an internal HTTPS backend, so matching only a literal `listen 443` in an Nginx HTTP server would be wrong. The exact certificate/domain and SNI chain must be attested. A mere `nginx -T` substring check is NOT a deployment gate.

U-OPTI's legacy FRP XHTTP renderer must not delete or overwrite the Smite-owned snippets, and must not silently add a conflicting route for the same `port/path`. The new host helper must refuse to adopt an existing unmanaged `49328` rule; that **HOLD is expected**, not a reason to delete the proven working route.

## Minimum implementation work before any U-OPTI release

1. **Approval and baseline**: read-only IR/KH preflight, verify current U-OPTI `INSTALL_REF` on *each* host, Smite Panel RC5 and both Nodes RC4, actual Nginx effective server and `nginx -T`, existing XHTTP paths, signed owner, two FRPC, unchanged FRPS PID. Verify off-server encrypted backups, distinct IR/KH snapshots and emergency console access.
2. **U-OPTI bridge installer**: create `/etc/nginx/smite-xhttp-routes` and bridge with trusted ownership/modes **only** after proving exact TLS/443 entry ↔ backend server. Stage a single include in the U-OPTI-owned host backend, back it up, `nginx -t`, guarded reload and scoped rollback; never rewrite the legacy 45121/49328 file. No duplicate server blocks, no new public ports.
3. **KH read-only Sanaei provisioner**: independently approved read-only bind mount of the existing 3x-ui instance 01 SQLite database into the KH Node at the reviewed path. Verify schema/UID/readability, WAL semantics, and that no client UUIDs or secrets leave the KH host. Inventory endpoint stays disabled by default until explicitly prepared.
4. **Privileged broker + signed lifecycle**: define narrow, signed Node-to-root IPC authorization, exact tunnel+lease+port+path match, durable transaction/idempotency ID, replay rejection, crash recovery. No `sudo` wildcard, no `docker exec` remote shell or accepting direct HTTP root commands. Signed IR owner and KH inbound proof before route change. Ambiguous KH Apply remains pending, not retried automatically.
5. **Reconciliation/ownership**: preserve existing U-OPTI route timer state; prevent old U-OPTI full-file renderer and new per-inbound manager from colliding. Implement controlled remove with signed KH absence + signed IR absence before lease/route release. No FRPS restart on adding a child.
6. **Simple install/update flow**: version-pinned Smite Panel/IR Node/KH Node pair with signed image/revision verification, strict trust/replay store, role-specific installer and restart/backup recovery; FRP/Backhaul remain optional independent modules. U-OPTI updates must preserve `INSTALL_REF` and avoid unreviewed download from main. Simple Persian/English wizard in Smite UI.
7. **Isolated and real tests**: unit/security and Nginx `nginx -t` fixture tests; **new disposable IR/KH VMs**, not the working pair. Test third port (e.g. 52000, only if an actual KH inbound is created), matching non-default XHTTP path, duplicate port/path, hidden/unavailable DB, conflicting Nginx owner, forced failed reload, power/reboot/replay restore, two simultaneous prior clients, manual add/remove, fresh install from zero and real TLS/443 client traffic. Validate real traffic instead of inferring it from HTTP listener/health.
8. **Publish and optional field cutover**: separate reviewed U-OPTI PR/CI and Smite PR/CI; immutable compatible release pair, independent signature verification and exact SHA. Only after successful clean-room tests, explicitly agree to a maintenance window for IR/KH. NEVER update Grandoptical.

## Execution sequence and hard stops

**Recommended sequence:** Smite source foundation and U-OPTI compatibility contract → host bridge and secure KH inventory mount PRs → signed broker / automatic wizard PRs → CI → clean disposable VPS test → pinned U-OPTI update + signed Smite candidate install on disposable hosts → 3rd inbound real-client test → release review → optional change to existing working IR/KH.

**Not now:** pressing U-OPTI menu Update on current IR/KH, enabling `smite-frp-xhttp` timer, copying the root helper to a running host, editing `45121` or `49328`, `Reapply All`, altering `main`, RC5 tag, or the separate Grandoptical server.

## Operator answer (فارسی)

**بله، U-OPTI باید برای نصب خودکار امن Nginx و اتصالش به Smite به‌روزرسانی بشود، اما اول کدنویسی و تست، بعد آپدیت سرورها.** اگر همین الان U-OPTI سرورهای IR/KH را آپدیت کنیم، مشکلِ نداشتن اتصال امن ویزارد Smite به Nginx حل نمی‌شود و احتمال تداخل با دو مسیر سالم وجود دارد.

هدف نهایی: نصب U-OPTI/Smite و اتصال Nodeها، انتخاب FRP در پنل، انتخاب اینباند سنایی، ساخت یک FRPC جدید روی KH و یک مسیر تاییدشده روی Nginx ایران پشت 443، بدون FRPS دوم و بدون دستور دستی برای هر اینباند.


## 2026-10-26 source implementation checkpoint

- U-OPTI [PR #48](https://github.com/aghajani82/u-opti/pull/48), head `f872ce07c78fbe2d8654c61bde31780a54b8b976`: 16/16 general CI jobs plus the five triggered focused workflows passed.
- Smite [PR #32](https://github.com/aghajani82/Smite/pull/32), head `c0c93506016a784e3d2a5103941084b72910a9da`: all 12 workflows triggered for this commit passed.
- Root authorization remains per-child and operator-asserted. Missing authorization holds before nonce consumption; uncertain broker outcomes are not retried.
- Remaining acceptance is a clean disposable dual-Ubuntu trial with a third real KH XHTTP inbound and a real TLS/443 VLESS client, followed by reboot/reconnect and rollback checks. No production or current trial host deployment is claimed.
