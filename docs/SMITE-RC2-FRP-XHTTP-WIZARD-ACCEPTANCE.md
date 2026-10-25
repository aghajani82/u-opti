# Signed RC2 FRP/XHTTP — Stable Baseline, Beginner Wizard and Acceptance Gates

**Date:** 2026-10-25  
**Status:** LAB traffic PASS; release HOLD. Feature-only until owner approval.  
**Scope:** Disposable IR + KH; **never** Grandoptical. **Do not merge main** until remaining gates close.  
**Source:** [PR #48](https://github.com/aghajani82/u-opti/pull/48), [Issue #47](https://github.com/aghajani82/u-opti/issues/47).

## Gate 1 — Preserve the proven working IR/KH baseline

Operator independently verified a working VLESS/XHTTP client using `ir.kolbe1.ir:443` and path `/45121/www`, arriving at KH 3x-ui through signed RC2 Smite FRP/WSS.

- `node-ir` / `node-kh`: Connected, IP can be N/A; use signed WSS, no IP hack.
- Existing UI tunnel `trial-frp-45121` (never duplicate) ACTIVE after single-row Reapply.
- IR ports 7000 and 45121 listen on loopback; KH VLESS `xhttp` port 45121 loopback, internal security none, Path `/45121/www`.
- IR single-443 Nginx :8443 publishes two managed XHTTP locations to local 45121. KH-only WSS :8444 SNI/source allowlist unchanged.
- IR one-shot publisher `smite-frp-rc2-xhttp-publish-45121.py`: COMMITTED and separately verified PASS_READ_ONLY. Auto-sync timer remains **inactive**.
- Backhaul and private networking independent and untouched.
- An FRP token was shown in an earlier screenshot; rotation before production must be coordinated across both parties; never include UUID/tokens or raw Compose/env/DB in outputs.

**Operator step:** Take independent provider Snapshots of BOTH IR and KH now that the connection is working. Name distinctly (e.g. `smite-rc2-ir-frp-xhttp-pass-20261025`, `smite-rc2-kh-frp-xhttp-pass-20261025`), note image ID and snapshot timestamp in a PRIVATE operator record. Do not upload secrets or snapshot contents to GitHub. Snapshot completion is NOT presumed unless operator confirms.

**Before any planned reboot/recreation:** Collect read-only, redacted Node health, TLS, listener binding, route checks; confirm snapshots and consoles exist; then plan a separate opt-in restore/restart test. No automatic restart here.

## Gate 2 — Integrate dynamic XHTTP route publishing into simple U-OPTI menu

The existing Standard FRP Beginner Wizard is extended with a new **4) PUBLISH** action. Advanced moves to option 5; existing foundation, PORT+PATH stage and VERIFY remain. No new competing menu.

**Correct user sequence:**
1. Install IR Smite/Panel + KH Smite/Node independently in Standard mode, signed and through TLS 443.
2. Install KH Sanaei and configure any valid VLESS/XHTTP inbound port to bind only `127.0.0.1`; save custom Path. It need not begin with the port.
3. On IR, choose **2) PORT + PATH** and stage exact matching saved profile first; this does NOT publish a route.
4. Create/Apply **exactly one** matching FRP TCP tunnel in the existing Smite UI. Set IR server role and KH client, use local FRPS 7000 and matched forwarded port. Do not create duplicates.
5. On IR, choose **4) PUBLISH**; the new `smite-frp-rc2-guided-publish.py` uses the selected **already-applied** port from trusted Node state, the saved validated registry Path, the pinned renderer and Signed RC2 security gate. It verifies all previously published routes and **refuses to publish any additional unapproved ports**, asks for operator approval twice (menu + exact Python TTY challenge), takes private journal+backup, atomically publishes only the approved route, tests/reloads Nginx, verifies Panel HTTPS. Failed postcondition triggers guarded rollback. No timer is enabled.
6. On IR, choose **3) VERIFY** and separately test a REAL authenticated client with IR domain, TLS 443, matching XHTTP Path.

**Safety constraints:** Existing routes preserved byte-for-byte; Nginx destination remains loopback. Engine lock busy -> explicit HOLD, not silent Bash abort. Existing already-published port -> read-only verify, no reload. Missing saved profile/tunnel, unexpected rendered route, timer already active, untrusted files, sidecar overlap, non-loopback listener, signed/WSS gate regression -> HOLD. No silent automatic FRP Reapply, Node restart, KH edits, token print, Backhaul install, shared port 7000 exposure or production mutation.

**Known limitation:** The new module is deliberately a **manual per-port opt-in publisher** for signed RC2; it does NOT yet implement startup/after-Reapply self-healing, automatic daemon/timer reconciliation, fresh signed image distribution, or all-provider portability. Those must pass separate reboot/recovery field trials and security tests. The previous port-45121 one-shot file stays as an auditable lab transaction (not an installer default).

## Acceptance before final release

- [x] Real VLESS/XHTTP client through IR domain working
- [x] One-route reviewed IR Nginx publication COMMITTED and VERIFY PASS
- [x] New generic per-port publisher implemented on PR branch, with offline tests
- [x] Beginner wizard updated and installer/updater file manifests integrated on PR branch
- [ ] Latest PR HEAD CI and independent signed verification SUCCESS
- [ ] Provider snapshots of both IR and KH explicitly confirmed by operator
- [ ] New generic publisher read-only `status --port 45121` on IR confirms `ALREADY_PUBLISHED`
- [ ] Reboot / replay / recovery trials preserve route and signed trust on disposable machines
- [ ] New *different port and arbitrary custom Path* end-to-end client PASS without affecting first port
- [ ] Coordinated rotation of exposed FRP token, with recovery plan and re-test
- [ ] Backhaul independence and installer clean-rebuild acceptance
- [ ] Release approval, target branch review, main merge and version/tag only after owner confirms

**Rule:** Revisions only in `feature/uopti-smite-closeout-integration-20261019` before explicit authorized merge. Preserve Grandoptical without exceptions.
