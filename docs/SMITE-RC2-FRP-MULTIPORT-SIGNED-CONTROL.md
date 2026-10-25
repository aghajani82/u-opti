# Smite RC2 — Multi-inbound FRP on one signed WSS 443 gateway

**Status: ARCHITECTURE / LIVE SECOND PORT HOLD. No changes to running IR or KH.**  
**Field trial:** 2026-10-25, IR + KH disposable VPS. `Grandoptical` prohibited.

## Verified live state

| Gate | Status |
|---|---|
| IR 45121 (owner trial-frp-45121) | Active, 127.0.0.1:45121 LISTEN, public https://ir.kolbe1.ir:443 /45121/www client PASS |
| IR FRPS | 127.0.0.1:7000 LISTEN behind Signed WSS gateway on public 443 |
| IR 49328 second profile | Saved `49328 -> /49328/sso` in private registry; Nginx route still absent |
| KH 49328 VLESS/XHTTP | Ready; private 127.0.0.1:49328 listener; path /49328/sso |
| Smite second trial-frp-49328 | Error: `Iran node error: Signed Node control unavailable`; IR :49328 NOT LISTENING |
| Signed node-ir identity + origin + pairing master | PASS (identity unique, active, signed_checkin, approved origin role/name, paired key available) |
| IR signed agent strict + engine | STRICT, MANAGED; identity, Replay file perms, replay enrollment binding, quarantine CLEAR |
| IR replay schema, tables, identity, quick_check | PASS |
| FRP engine inventory | READY |
| Panel to pinned IR agent | Unsigned GET /api/agent/tunnels/apply -> HTTP 405; proves routing, **not signed POST approval** |

## Source-level defects to address before second tunnel

At Smite source snapshot `97bc67be1b0e16763935cb3383bcefca70fa5b2d` (and core adapter still same blob in main):

1. `panel/app/node_client.py::_signed_agent_request` collapses signed HTTP errors, transport exceptions and other signature failures to the same UI string `Signed Node control unavailable`. A GET 405 or replay DB offline checks cannot reveal which POST Apply step failed.
2. `panel/app/routers/tunnels.py` in new/re-Apply flows creates a **per-tunnel** FRP token, prepares an FRP server spec with `bind_port=7000`, and dispatches an independent signed Apply on node-ir. The second FRP row has a different tunnel ID.
3. `node/app/core_adapters.py::FrpAdapter.apply` launches a **new frps process per server tunnel ID**, each trying to bind `127.0.0.1:7000` in signed WSS mode. If second signed Apply is admitted, this can collide with the existing owner. Setting another external FRP control port would break the single-443 policy and is not an acceptable workaround.
4. The U-OPTI beginner wizard now supports guarded one-port-at-a-time **Nginx route publishing**; it cannot fix or bypass Smite's missing multi-port FRPS orchestration. Do not publish 49328 while IR 49328 listener absent.

## Proposed fail-closed architecture — design for implementation, NOT deployed

- Maintain **one** trusted FRPS owner on IR at loopback `127.0.0.1:7000`, with the existing signed WSS 443 transport. A new remote-forward port is a **proxy under that server**, not a new FRPS daemon.
- Add an explicit **managed shared-FRPS resource ID**, owner/lease metadata, immutable FRPS token association and validated port allocations. No secrets in UI, logs or GitHub. Never silently use a second token with an existing daemon.
- Smite Panel must authorize adding/removing a proxy to the existing **signed** resource; `node-ir` must validate signed Node identity, managed engine availability, owner/service readiness, identical gateway transport, absence of remote-port conflict and allow only loopback local proxy binding.
- KH continues to create one `frpc` proxy per independent port using the approved FRPS instance. Keep the existing 45121 FRP session intact; do not restart FRPS or global ApplyAll to add 49328.
- Make lifecycle **idempotent and recoverable**: new proxy journal, exact create/update/remove scope; after reboot reconstruct one shared FRPS before child FRPCs; refusing owner removal while other ports active; rejects duplicated port, unknown path or unauthenticated operation. On failure, roll back **only** the new proxy, never replace/restart the owner.
- IR U-OPTI guarded per-port XHTTP route publisher can publish `/49328/sso` **only after** Smite reports new proxy active and IR `127.0.0.1:49328` LISTEN. Existing Nginx `/45121/www` preserved byte for byte.
- Test multi-port end to end under Signed RC2: 45121 client stays connected while 49328 proxy is attached, 49328 client works, denied unknown port/path, no public :7000/:45121/:49328, failed signed auth 401, missing replay 503, engine-not-ready 409, conflicting port HOLD, second-stage replay, restart/recovery, explicit rollback, Snapshot restore.
- Migrate old per-tunnel FRP safely; **do not** silently reinterpret currently running trial-frp-45121 state. The running signed RC2 snapshot stays intact pending a separate operator-approved migration plan.

## Immediate non-mutating diagnosis

Retrieve ONLY counts of HTTP status responses for `POST /api/agent/tunnels/apply` from node-ir logs (401/403/409/500, etc.) and generic FRPS bind-errors, never raw logs/token/UUID; if no matching access logs, classify `NO_EVIDENCE`, not success. Correlate with operator's single-row attempted Reapply; don't retry blindly. Do not send a signed POST until a reviewed, idempotent command/reconciliation plan exists.

## Release gates

- [x] 45121 live VLESS/XHTTP works and both IR/KH read-only baselines PASS
- [x] 49328 profile and KH inbound read-only preflight PASS
- [x] Panel and Node identity + replay + FRP engine audits PASS
- [ ] Exact failure category of signed Apply independently determined
- [ ] Shared FRPS singleton architecture implemented + tests in isolated Smite feature branch, no main direct edits
- [ ] Adapter restore, concurrency, external bind, token isolation and rollback reviewed
- [ ] Dedicated disposable acceptance trial with both 45121 and 49328 alive concurrently
- [ ] U-OPTI easy wizard + safe route publishing field test on second port
- [ ] Owner-approved merge to main and release; Grandoptical never touched

Related: [U-OPTI draft PR #48](https://github.com/aghajani82/u-opti/pull/48), [project Issue #47](https://github.com/aghajani82/u-opti/issues/47).
