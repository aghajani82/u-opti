# U-OPTI independent Backhaul — usability and standalone design (2026-10-15)

**Branch:** `feature/smite-standard-backhaul` | **Draft PR:** #18 | **Production:** NOT APPROVED

This records the operator's live KH+IR guided-install test and four high-priority changes. The new guided installer returned `GUIDED_TEST_HOST_INSTALL_LOCAL_CHECKS_PASSED` on both hosts, and the operator independently confirmed a working Backhaul client. That does **not** prove FRP, reinstall/rollback, arbitrary routing, or production safety. The existing pilot's shared token was exposed in a chat and MUST NOT be reused for production.

## Priority 1: configurable data port and XHTTP URI

Never require Xray to listen on `56053` or use `/56053/www/`. For example, a valid user-selected profile is:

- IR: `ir.example.com` public TLS:443 at Nginx
- KH Xray: VLESS/XHTTP at **127.0.0.1:45123** with URI **`/assets/v1/connect/`**
- Backhaul IR server: local WebSocket control listener, separately configurable
- Backhaul IR forwarded data listener: **127.0.0.1:45123** mapped to KH Xray **127.0.0.1:45123**
- KH bridge: its own **127.0.0.1** port, separately configurable
- Client: IR FQDN and TLS SNI; XHTTP URI **`/assets/v1/connect/`**.

Do not conflate the **public TLS entry port**, **local control listener**, **local data listener**, **KH target port**, **KH bridge listener**, and **XHTTP URL path**. Backhaul v0.7.2's control endpoints `/channel` and `/tunnel/` are protocol-specific, not user-editable XHTTP paths. Reject these namespaces, FRP numeric `/PORT/web` collisions, unsafe characters and injection. Reject occupied or exposed local ports. Validate that KH Xray and IR XHTTP paths match, including trailing-slash normalization. Preserve unrelated Nginx locations (website, FRP, Smite) and existing clients.

**Implemented first:** the *OFFLINE-ONLY* renderer and Sidecar candidate generator now accept safe non-default data ports and independent XHTTP paths, with synthetic tests; defaults remain for backward compatibility. **NOT YET IMPLEMENTED:** passing the selected profile through guided preparation, manifest reconciliation, live installer, persistent local profile, readiness, rollback and both-host traffic tests. The live installer MUST continue using only its fully validated legacy topology until all of these are integrated; do not silently accept a custom profile that the installer cannot honor.

## Priority 2: one role selection, clear navigation

Present IR/KH selection **once before** the Tunnel Management protocol menu, or detect a trusted existing host role. Carry the role into FRP and the Control Center. If a trusted installed role contradicts selection, HOLD; never silently reinterpret IR as KH. Do not put a second IR/KH selector under an unrelated menu, and never make server-role choice an install approval.

Top-level:
```text
Tunnel Management — current server IR [or KH]
1) Backhaul — independent tunnel
2) FRP — Smite Standard tunnel
3) Rathole — design-only
4) Diagnostics / Control Center
0) Back
```

Backhaul, **new beginner order**:
```text
1) Pair IR/KH (private copy/paste in two Bitvise terminals)
2) Install Backhaul on THIS server (explicit test-only consent)
3) Check status and troubleshoot
4) Client configuration
5) Recovery and advanced tools
0) Back
```

The main Backhaul pairing option must display a clear role-specific action (IR generates code; KH pastes hidden value). During each wizard step, show current server role prominently. Diagnostics and recovery must not be interleaved with the install flow.

**Implemented:** reordered Backhaul main navigation, read-only diagnostic submenu, one-time role selection, role propagation to FRP from both top-level and Control Center, conflict guard and regression tests. **Outstanding:** streamline FRP's own setup steps and advance automatically to the next eligible action based on journal; avoid causing side effects in a display-only screen.

## Priority 3: standalone without Smite Panel, Smite Node or FRP

The **independent Sidecar must not require** `/etc/u-opti/smite/state.env`, the `smite-panel` or `smite-node` container, the FRP process on IR localhost:7000, or Smite's fixed backend file `/etc/nginx/conf.d/u-opti-smite-panel-backend.conf` and port :8443. These are currently coupled in role pairing, readiness and the strict Nginx proposal compiler. It is NOT safe to simply bypass a preflight flag.

Create an isolated standalone installation mode, explicitly selected by the operator:

1. Select and verify role IR or KH and persist securely in an **U-OPTI-owned** root-only role declaration that is independent of Smite. Reject a contradictory existing Smite role or previous Sidecar.
2. Check only actual prerequisites: root, Docker or vetted native binary execution, TLS certificate/DNS/HTTPS Nginx entry and named vhost on IR, reachable KH bridge via TLS/SNI, and an existing KH target service. **Smite and FRP are optional.** If the requested target is VLESS/XHTTP, KH Xray inbound is required; Backhaul transport itself must not force 3x-UI.
3. Use independently owned Nginx includes in a user-confirmed known vhost. If the vhost layout cannot be safely identified, HOLD with a precise instruction rather than rewriting arbitrary files. Never take over an existing :443 vhost or change unrelated web paths.
4. Generate a private, authenticated Backhaul token and bind every locally exposed non-public port to loopback. Do not log/show it except during an explicitly acknowledged transfer step.
5. Use the existing tested **transactional journal, original-vhost backup and guarded rollback** model, extended to track standalone resources, profile values, Nginx versions, and manifest checks.
6. Perform two-host real authenticated client test, FRP preservation when FRP happens to coexist, public bridge-forwarding denial, and sequential reboot tests.

Smite-integrated mode may stay available under FRP/Advanced, but **Stand-alone Backhaul must have its own installation path and menu independent of installing Smite**.

**Not yet implemented:** these new standalone admission, discovery, deployment and rollback rules. The existing installed trial remains **Smite-baseline only**; do not advertise it as standalone capable.

## Priority 4: validation and acceptance

Before enabling the new live standalone/custom-profile button, CI and field tests must include:

- default and custom ports/path across **both** IR and KH and a real authenticated VLESS/XHTTP client;
- fresh IR/KH VPS **without** Smite, FRP, 3x-UI, or Smite state files (with Nginx and a manually provisioned KH target service only);
- safe route collision refusals (website, `/channel`, `/tunnel/`, FRP `/PORT/web`), occupied ports, invalid listener owners, symlinks, conflicting roles and certificate verification failures;
- pairing first, install second, health test third, errors with actionable **non-secret** reason categories;
- independent Trial approvals/snapshots and explicit irreversibility warning; guard against duplicate install and mid-transaction interruption;
- safe uninstall/reinstall/rollback trial only, original Nginx byte preservation, sequential reboot, and Smite/FRP coexistence unchanged.

All new work stays on the draft PR until CI and live separate-host verification succeed. The current one-flow installer is safe only within its intentionally strict existing host layout. Never use the exposed trial token on a production server.
