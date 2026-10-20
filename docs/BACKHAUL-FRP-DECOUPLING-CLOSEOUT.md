# Backhaul independence closeout — legacy prepare fix vs real host installer

**2026-10-20 | Existing [Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) | [Issue #47](https://github.com/aghajani82/u-opti/issues/47)**

**Status: BACKHAUL CANDIDATE PREPARATION DECOUPLED / LIVE INSTALL STILL HOLD.**

## Root cause and actual change

The U-OPTI repository contains TWO historically separate Backhaul tracks:

- **Legacy Standard overlay preparation** in
  `modules/smite-backhaul-management.sh`: previously required a local FRP
  server listener on `127.0.0.1:7000` on IR and a fake fixed Sanaei Xray
  listener `127.0.0.1:56053` on KH, even though the operation **only
  staged** files. It also rendered a dangerous example `ir-xhttp.conf`
  that assumed a KH inbound `56053`, `/56053/www`, and a particular KH
  domain without any operator selection.
- **Managed independent engine** in
  `modules/smite-managed-backhaul*.py` + `smite-managed-backhaul-menu.sh`:
  already prepares a pinned **Backhaul v0.7.2** artifact without installing
  FRP and with `FRP_DEPENDENCY=NONE`. It is a **CI-tested, host-read-only,
  intentionally unactivated** candidate, not a released on-host installer.
  Its security baseline is a reviewed managed/strict Smite Core; this does
  **not** require the FRP engine to be present.

### Changes in this closeout commit

1. In the **legacy offline preflight only**, remove the check requiring
   `127.0.0.1:7000` FRP and the check requiring a KH Xray listener on
   `127.0.0.1:56053`. IR only preflights the Backhaul candidate control
   port `3080`; KH retains conservative `13080` bridge reservation in
   the *old* preview. Do not modify any real running FRP, Nginx, Smite or
   Xray service.
2. Stop rendering `ir-xhttp.conf` with invented live-looking
   `56053`/`/56053/www`/KH-domain values. Instead stage **only**
   `IR-XHTTP-NOT-CONFIGURED.txt`. This is deliberately NOT an Nginx
   snippet and says to select the **actual** KH Sanaei inbound port,
   path and upstream hostname after Core and Sanaei installation.
3. Update the ordinary Backhaul wizard *overview* to display this
   deferred dynamic-port/path flow instead of telling beginners
   that `56053` and `/56053/www` are the required values.
4. Extend existing regression tests
   `tests/test-smite-backhaul-management.sh` to mock **NO FRP listener
   and NO Xray inbound** for BOTH roles, still pass the independent
   preparation/integrity tests, assert there is no fabricated
   `ir-xhttp.conf`, and leave existing live process fixtures alone.
   `tests/test-smite-tunnel-wizard.sh` requires no misleading fixed
   `56053` in the beginner overview and keeps its dynamic
   real-installed-profile test.

## Frozen five-step operator flow

1. Install Smite Core/gateway on **IR**, independent of tunnel engine.
2. Install Smite Core/gateway on **KH**, independent of tunnel engine.
3. Install Sanaei/3x-ui on KH; create its actual chosen XHTTP inbound.
4. In a **separate** route menu enter/inspect the selected inbound
   loopback port, path and hostname. No fixed `56053`; no port prompt
   during engine binary installation.
5. Choose Backhaul, FRP or both **independently**, pair/authenticate,
   apply and test tunnel only after explicit production admission.
   The shared Node Compose/manifest requires a transaction lock and
   must preserve the other engine and signed/replay storage.

The current work completes the **safe preview/UX decoupling**, not Step 5
production activation. The old legacy path is NOT to be promoted as a
general host installer: it still requires old Docker overlays and a
compatible running Smite Node. The managed path and strict signed
restore guarantees remain under review.

## Release blockers: do not obscure behind green CI

- No approved production host engine-install transaction/executor and
  signed cross-host postrestart admission yet. Existing managed
  install/rollback operates in marked disposable GitHub CI sandboxes.
- Real effective IR→KH TLS443 gateway route, Xray dynamic inbound and
  HMAC / replay / token remain unproven together under actual on-host
  Backhaul installation; preserve strict route collision checks.
- Still need immutable reviewed Panel+Node image release provenance,
  authorized stale Replay restore/key rotation, snapshot-backed dual-VPS
  reboot and rollback with separately granted approval.

`MAIN_MERGE=NO` · `RELEASE_PUBLISH=NO` ·
`INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD` ·
`IR_KH_UNCHANGED=YES`.
