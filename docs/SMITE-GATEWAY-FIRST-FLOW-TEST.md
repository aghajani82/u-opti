# Smite Gateway-First Flow Test

This document is for the experimental branch `feature/smite-gateway-first-flow` only.

The branch is intentionally **not merged to `main`**. Its purpose is to validate a cleaner first-install flow before promotion.

## Goal

Keep the validated v0.15.0 public-port architecture unchanged while removing the temporary SSH local-forward requirement for creating the first Backhaul tunnel.

Public exposure remains:

- TCP `80` — Nginx / ACME / HTTP handling
- TCP `443` — Nginx shared entry
- No new public service ports

Internal/private listeners remain internal/private, including Smite `8000`, node `8888`, Backhaul control `3080`, Panel TLS backend `8443`, Backhaul data backend `9443`, EasyTier internals, and the chosen Xray loopback inbound.

## What changes in this branch

In Private Network mode, the Iran `443 Gateway` may now be configured **before the first Backhaul tunnel exists**.

The Panel therefore becomes reachable immediately at:

```text
https://<iran-panel-domain>
```

When the first Backhaul tunnel is later created in Smite with logical/public port `443`, the Iran Smite node runtime maps that Backhaul data listener to:

```text
127.0.0.1:9443
```

Nginx remains the only public owner of TCP `443` and forwards RAW/default traffic to that loopback Backhaul listener.

The Smite UI can therefore continue to use the normal logical Backhaul value `443`; the user does not need to enter `9443` in the Smite tunnel form.

## Test branch install

On each clean rebuilt server:

```bash
export U_OPTI_BRANCH=feature/smite-gateway-first-flow
curl -fsSL "https://raw.githubusercontent.com/aghajani82/u-opti/$U_OPTI_BRANCH/install.sh" -o /tmp/u-opti-install.sh
bash /tmp/u-opti-install.sh
```

The menu should show test version `v0.15.1`. This is a branch test identifier, not a published stable release.

## Recommended clean test order

1. Rebuild Iran and Foreign servers.
2. Update/reboot the OS if required.
3. Install this U-OPTI branch on both servers.
4. Install Docker on both servers.
5. Foreign: install Sanaei 3x-UI with its Foreign domain so Nginx/TLS exists.
6. Foreign: `Docker Management -> Smite Management -> Private Network -> Initialize Foreign / KH`.
7. Foreign: show Pairing Details and retain the domain, hidden path, and secret privately.
8. Iran: initialize EasyTier Panel / Iran from those pairing values.
9. Verify EasyTier overlay connectivity (`10.89.10.10 <-> 10.89.10.20`).
10. Iran: install `Smite Panel + Iran Node` in Private Network mode with `10.89.10.10`.
11. Foreign: install `Smite Foreign Node` in Private Network mode with Iran `10.89.10.10` and Foreign `10.89.10.20`.
12. **Iran: configure `Smite Management -> 443 Gateway -> Configure / Repair Panel Gateway` now, before any Backhaul tunnel exists.**
13. Confirm the Smite Panel opens directly through its HTTPS domain. No Bitvise/C2S forward to port `8000` should be needed.
14. Foreign 3x-UI: create an Xray/VLESS inbound bound to loopback. `127.0.0.1:10000` is the recommended test value, but `10000` is not mandatory.
15. Smite Panel -> Tunnels -> Create Tunnel:
    - Iran Node: the Iran node
    - Foreign Server: the Foreign node
    - Core: Backhaul
    - Type: TCP
    - Control Port: `3080`
    - Ports: `443`
    - Token: empty / auto-generated
    - Allow UDP over TCP: off
    - v4 to v6: off
16. Advanced -> Custom Ports:

```text
443=127.0.0.1:10000
```

If the Xray inbound uses another loopback port, replace only `10000` with that port.

17. Create the tunnel and verify it becomes Active.
18. Iran runtime should show Nginx on public `443` and Backhaul on loopback `127.0.0.1:9443`.
19. Verify Backhaul control connections use EasyTier `10.89.10.10:3080`.
20. Test the VLESS client end-to-end.
21. Reboot Foreign and retest.
22. Reboot Iran and retest Panel + VLESS again.

## Expected final listener model

Iran:

```text
public 80            -> Nginx
public 443           -> Nginx stream/SNI gateway
127.0.0.1:8443       -> Smite Panel TLS backend
127.0.0.1:9443       -> Backhaul data
10.89.10.10:3080     -> Backhaul control path over EasyTier (provider-public blocked)
10.89.10.10:8000     -> Smite private Panel API (provider-public blocked)
```

Foreign:

```text
public 80/443        -> managed Nginx/TLS entry
10.89.10.20:8888     -> Smite node control (provider-public blocked)
127.0.0.1:10000      -> example Xray target
```

Provider/public firewall policy should continue to expose only the intended public web entry ports (`80` and `443`, plus the separately managed SSH access rule used by the administrator).

## Pass criteria

The branch is ready for further cleanup/promotion only if all of these pass on a clean rebuild:

- Gateway config succeeds with **zero** Backhaul tunnels.
- Panel HTTPS works immediately after Gateway configuration.
- No SSH local forward to Panel `8000` is needed.
- Creating Backhaul with logical port `443` succeeds while Nginx already owns public `443`.
- Actual Backhaul data listener is `127.0.0.1:9443`.
- Public exposure remains unchanged.
- VLESS works end-to-end.
- Foreign reboot restores the full path.
- Iran reboot restores the full path.

Do not merge this branch to `main` until the clean test passes.
