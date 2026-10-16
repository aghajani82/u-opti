# Standard FRP — custom VLESS/XHTTP base Path (15 Oct 2026)

Repository: aghajani82/u-opti | Branch: feature/smite-standard-backhaul | Draft PR #18

## Root cause and fix

The previous Standard FRP gateway reconciler read only the TCP forwarded
port from Smite's IR tunnels.json and hardcoded Nginx routes /PORT/web
and /PORT/web/. Changing KH Sanaei's XHTTP path to /PORT/shop left the
IR gateway without a matching route. This was U-OPTI behavior, not a
limitation of Xray/XHTTP.

The reconciler now reads an optional private per-port registry on IR:
  /etc/u-opti/smite/frp-xhttp-paths.json
When unset, each port retains the legacy default /PORT/web. A custom
/13914/shop yields two Nginx locations: exact /13914/shop and prefix
/13914/shop/. Both proxy the original client URI unchanged to the
Smite FRP TCP forwarded port on IR.

The registry is root-owned and 0600 and persists across auto-sync,
U-OPTI code updates and reboot. Do not edit it by hand.

## Rebuilt two-host test procedure

1. Only use disposable rebuilt IR/KH hosts with snapshots, backups,
   console access, and U-OPTI from feature/smite-standard-backhaul.
2. Set up working Smite Standard FRP, DNS, certificates, WSS/443, and
   Nginx first. Use a different port and path than Backhaul.
3. Example KH Sanaei FRP inbound: VLESS, XHTTP, bind 127.0.0.1,
   port 13914, mode auto, security none, base path /13914/shop
   WITHOUT the trailing slash.
4. In Smite UI, create and apply FRP TCP: IR server, KH client,
   FRPS bind port 7000 on loopback; forwarded TCP port 13914.
5. On IR in U-OPTI Standard FRP Setup Wizard -> Step 5, confirm that
   the Smite FRP tunnel exists and choose to register a custom IR path.
   Enter forwarded port 13914 and path /13914/shop.
6. The wizard verifies the applied server tunnel, validates the path,
   checks existing known Backhaul routes, atomically stores the mapping,
   and reconciles Nginx. A failed reconcile restores the prior path;
   never force a retry after an unexpected error.
7. On IR, Step 1/4 displays managed locations; Step 6 probes
   https://IR-DOMAIN/13914/shop/ over HTTPS:443.
8. On KH, Step 6 asks for /13914/shop and probes loopback Xray at
   http://127.0.0.1:13914/13914/shop/. KH does not read IR's
   mapping; Sanaei path and IR gateway must be configured identically.
9. IR Step 7 displays the configured public client path /13914/shop,
   with IR TLS hostname, port 443, SNI, and ALPN http/1.1. Verify
   real authenticated VLESS/XHTTP traffic (not merely OPTIONS).
10. Verify FRP and Backhaul separately, then reboot hosts one by one,
    confirming the custom FRP mapping survives auto-sync and reboot.

## Safety constraints

Safe paths use ASCII alphanumeric segments plus hyphens/underscores,
start with /, and do not end with /. Examples: /13914/shop,
or /store/v1. Reserved Smite endpoints, numeric paths belonging to
another port, overlaps with other active FRP paths and installed
Backhaul Sidecar are refused. The registry is IR-only.
An applied Smite FRP TCP server tunnel is required before registration.

The automated GitHub CI tests cover custom-path generation and
rollback, but real FRP authentication and reboot with a custom path
must still be field-tested. PR #18 remains Draft, not production-ready.

Backhaul example from user-confirmed test:
KH data port 17991, XHTTP base path /17991/shop.
Use a DIFFERENT port for the FRP experiment.
