# U-OPTI v0.16.0 — Standard FRP HTTPS/443

Release date: 2026-10-12

## Included
- Optional IR/KH Standard FRP wizard, independent from Private Network Wizard.
- FRP v0.71.0 WSS control via the existing IR domain and HTTPS/443 at `/~!frp`, local FRPS binding.
- Automatic validated XHTTP `/PORT/web` routes and persistence safeguards.
- Shared KH Smite Foreign Node/Sanaei Nginx HTTPS vhost with protected control path.
- Legacy 0.15.2 updater compatibility: absent FRP helper modules are fetched, Bash-validated and staged at the first start of the new U-OPTI executable.

## Tested
- Fresh rebuilt IR/KH, Smite/WSS control and real XHTTP/VLESS traffic.
- Operator-confirmed sequential host reboots and reconnecting client.
- CI shell, FRP, Nginx and legacy updater regression checks.

## Operational notes
- v2rayN tested client: IR Panel domain:443, XHTTP path `/PORT/web`, TLS SNI IR Panel domain, `ALPN=http/1.1`.
- Existing Private Network and installed tunnel settings are **not** migrated.
- A server installed from `fix/smite-frp443-persistence` persists that `INSTALL_REF`. The standard Update menu continues using its configured source; selecting `main` requires an explicit planned change.
- Module updates are not the same as reconfiguring live Smite/Xray/Nginx; operators must retain separate backups and validate Repair and renewal independently.
- Standard Backhaul is not part of this release and will be developed on `feature/smite-standard-backhaul`.
