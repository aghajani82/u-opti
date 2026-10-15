# Backhaul Sidecar – custom Xray/XHTTP guided install (experimental)

**Branch:** `feature/smite-standard-backhaul` | **PR:** #18 (DRAFT) | **Status:** CI-only validated. Do NOT merge to production yet.

## Operator request resolved in the guarded test installer

The Xray/3x-UI inbound port and XHTTP URL path are now TWO user-controlled settings. `56053` and `/56053/www/` are backwards-compatible defaults **only**, not required values. Example:

- **KH** Xray/3x-UI: listen **127.0.0.1**, port **45123**, XHTTP path **`/assets/v1/connect/`**, security None for Nginx-terminated TLS; add a legitimate VLESS user.
- **IR** public endpoint: `https://ir.example.com:443/assets/v1/connect/`. Nginx forwards XHTTP via the independent Backhaul server's local **127.0.0.1:45123** listener.
- **KH** Backhaul client: connects through the verified Nginx loopback TLS bridge, sends the tunneled bytes to **127.0.0.1:45123** and existing Xray inbound. The Backhaul WS control URLs `/channel` and `/tunnel/` are separate fixed protocol endpoints and are not XHTTP paths.
- Run the same user inputs on **both** test servers. No cross-server comparison of profile metadata is automatic yet; use authenticated end-to-end VLESS/XHTTP and check the local profile status on both.

## Guided beginner navigation

`Tunnel Management → Backhaul → 1) Pair IR/KH → 2) Install Backhaul`.

Both IR and KH show:

```text
IR HTTPS domain:
KH upstream / Xray Host domain:
KH Xray inbound port [56053]:
XHTTP path [/PORT/www/] (e.g. /assets/v1/connect/):
Selected KH Xray port: PORT | XHTTP path: PATH/
Type REBUILT-TEST-VPS ...
Type INSTALL-IR or INSTALL-KH ...
```

The wizard accepts a trailing slash on entry but canonicalizes and validates the path before rendering. It validates non-reserved port ranges, exact private Nginx + TOML proposal bytes, candidate manifest profile, loopback listener ownership, existing vhost hashes and journal safety, with no blind overwrite. The **same transactional test installer** is used, not a second unguarded deploy command. The installed TOML contains **non-secret comments** identifying the selected port and URI so read-only Status, Audit and Client configuration screens show actual values instead of fixed legacy examples.

A custom port cannot be used for WS control or Nginx bridge, and control `/channel`, `/tunnel/`, FRP `/PORT/web` URL namespaces are refused. The legacy fixed layout is preserved for already-tested default profiles. **No existing IR/KH VPS is changed by updating the repository.**

## Scope and remaining gates

This specific change removes the fixed **KH Xray inbound port and XHTTP path** from the *Smite-baseline experimental guided installer*. It does **not** remove the older Smite Panel/FRP prerequisites, Nginx file shape, or fixed Backhaul WS-control/loopback-bridge ports. Full **standalone without Smite** is a separately tracked incomplete feature (see `docs/BACKHAUL-STANDALONE-UX-2026-10-15.md`).

CI now performs exact private paired-candidate construction for both roles, rejects profile tampering, checks selected KH Xray listener admission, and checks the menu displays custom settings. CI is not a real two-host connectivity test. Before production approval, rebuild disposable IR+KH hosts with *non-default* inbound and path, install in matching order, verify one real authenticated VLESS/XHTTP client, FRP preservation, public bridge protection, sequential reboot and rollback. Retire exposed trial tokens before any non-disposable use.
