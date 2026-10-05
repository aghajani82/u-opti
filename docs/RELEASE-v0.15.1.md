# U-OPTI v0.15.1

Smite Private Setup Wizard is now the recommended guided workflow for two-server Private Network deployments.

Highlights:
- 10-step live verification flow with `1-10`, `.1-.10`, `n`, and `r` controls.
- Role-aware KH/Foreign and IR/Panel guidance with one `[~]` next-step marker.
- Runtime verification for Docker, 3x-UI, EasyTier, Smite nodes, Panel 443 Gateway, Xray loopback binding, Backhaul, and post-reboot recovery.
- Gateway-first Private Mode flow: Nginx owns public TCP/443 before the first Backhaul tunnel; RAW data is attached to loopback `127.0.0.1:9443` when the tunnel is created.
- Hardened local ACME readiness probe that bypasses proxy variables and tolerates fresh Nginx reload timing.
- Xray target verification requires loopback-only binding, preventing accidental `*:PORT` exposure from being marked complete.
- Reboot validation uses Linux boot IDs and validates each host independently.

Validated end-to-end on clean KH and IR servers, including client connectivity and reboot persistence. Also validated on Ubuntu 26.x during the final clean deployment test.
