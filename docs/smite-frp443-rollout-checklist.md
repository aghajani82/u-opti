# Smite Standard FRP / Shared Sanaei HTTPS Rollout — Draft Checklist

Status: **EXPERIMENTAL / DO NOT DEPLOY ON PRODUCTION**, PR #16 on `fix/smite-frp443-persistence`.

This document records the next steps so future changes do not silently replace the working Smite installation procedure or production FRP/XHTTP service.

## Non-negotiable compatibility boundary

- **Do not change the existing guided Smite installation sequence**, its Panel/Iran and Foreign role order, or the Private Network / EasyTier ten-step Wizard.
- The existing `modules/docker.sh`, `modules/smite-install.sh`, `modules/smite-setup-progress*.sh`, `modules/smite-private-network.sh`, and `modules/smite-easytier.sh` are guarded by `tests/test-smite-wizard-preservation.sh` against their PR base blob SHAs.
- Experimental Standard FRP must be opt-in and kept separate from Private Network and Backhaul; neither pathway should be auto-migrated to another provider.
- **Never deploy the draft branch to the active IR or KH servers without an explicit test/maintenance window, backup/snapshot and rollback plan.** The draft PR should not be merged into a release until clean installation is verified.

## Safe reboot order on the existing live setup (before snapshot/rebuild)

1. **IR first only**: check Smite Panel + Iran Node, Nginx SNI/443, FRPS listener and existing FRP/XHTTP client connection. Reboot only IR, then repeat the same checks. If any tunnel fails, stop and preserve KH unchanged.
2. **KH second, only after IR passes**: check Smite Foreign Node, Docker Sanaei, both HTTPS endpoints and FRPC reconnection. Reboot only KH, then repeat checks. If anything fails, stop before snapshots/rebuild.
3. Once *both* servers work after reboot, take verified, separate IR/KH snapshots. Export critical Docker volumes/databases/settings separately and verify provider console/SSH recovery. Do not destroy/rebuild the hosts until snapshots have been confirmed recoverable.
4. Rebuilding both hosts is an outage; test against the pinned draft branch, never accidentally download `main`. Keep a verified rollback target.
5. Read-only tests on the live hosts are not proof the new installer works; a clean-snapshot installation is the release gate.

## Current real-world evidence (October 11, 2026)

- KH: an existing Smite Foreign Node and freshly installed Docker Sanaei instance were successfully exposed on the same `kh.kolbe1.ir` hostname and TCP 443 **after manual Nginx consolidation**.
- The old Docker installer created competing `server_name kh.kolbe1.ir` HTTPS blocks: Sanaei returned HTTP 200 while Smite returned 404.
- Moving the IP-allowlisted Smite control location into Sanaei's managed HTTPS vhost restored both endpoints to HTTP 200.
- Duplicate HTTP/80 ACME Nginx configurations were consolidated; a local HTTP-01 file returned `ACME-OK`. `certbot renew --dry-run --cert-name kh.kolbe1.ir` succeeded.
- The new Docker Sanaei Xray inbound reportedly connects through the active tunnel. This is evidence of the **manual** deployment, not of the new installer automatically doing it.

## Draft improvements already committed

- Preserve IR FRP-over-TLS/SNI Nginx routing and existing HTTPS backend locations across Smite Gateway Repair.
- Preserve IP-allowlisted Smite control on a shared KH 443 host when the Docker Sanaei Nginx/SSL installer or Repair runs.
- Use one shared ACME/HTTP-01 vhost instead of emitting a duplicate; ensure HTTP-01 test files are readable despite restrictive root umask.
- Back up managed Nginx files/symlinks before shared activation; validate generated config and both endpoints; roll back after failure.
- Preserve standalone Foreign Gateway Repair and optional sharing of an existing Sanaei management path.
- CI exercises parser safety, shared HTTPS activation, idempotent Repair, simulated failures/rollback, and Wizard preservation.

## Required staged integration checks before release

1. **Compatibility and image review.** The default Smite v0.1.7 Docker image digests remain upstream and might not include `frp_gateway_config.py`. The **explicit Standard FRP Test Guide** now prepares a validated, read-only host overlay helper and compatible `core_adapters.py`, so no custom image is required merely for this helper. Offline CI confirms the helper behavior and Compose mounts; the resulting fresh-container runtime and FRPC-to-443 must still pass the live rebuild test. The legacy guided/Private Wizard is unchanged.
2. **Fresh IR setup (test server/snapshot only).** Run the existing guided Standard Panel + Iran Node flow unchanged, followed by IR Panel 443 Gateway. Confirm healthy Smite containers and accessible HTTPS control/API. Verify FRPS v0.71.0 binaries are present inside the containers.
3. **Fresh KH setup (test server/snapshot only).** Run the existing Foreign Node guided flow, configure its HTTPS/443 gateway, then install Docker Sanaei on **the same KH domain** using the normal installer. Confirm exactly one Nginx 443 vhost and one HTTP-01/80 vhost for that hostname.
4. **Security checks.** Smite control path must accept loopback and the configured real IR server IP, reject unrelated remote IPs, and never expose the Node API on untrusted public TCP/8888. Check that Sanaei panel/subscription/Xray paths and unrelated sites still work.
5. **FRP tunnel provisioning.** Create a disposable FRP Server on IR and Client on KH through the Smite UI. Check separate local FRPS listen port versus public FRPC gateway port 443, TLS/SNI allowlist, token authentication, reconnects and exact port forwards. Keep all existing VLESS/XHTTP paths and tunnels intact.
6. **Repair/reboot/renewal.** Run controlled Nginx/SSL Repair and Smite Gateway Repair on both test nodes, reboot each server, check FRP reconnection and `certbot renew --dry-run --cert-name <test-domain>`. Test failed Nginx validation and failed backend health to verify automated rollback.
7. **Release gate.** Require passing CI and the clean-snapshot end-to-end checks above; review the image pin, document upgrades/uninstall/recovery, then request approval before taking PR #16 out of Draft or merging. Do not automatically deploy to the real IR/KH nodes.

## Ownership / scope

- IR: Smite Panel + Iran Node; FRPS in private/local bind(s), public 443 via the dedicated IP-allowlisted TLS/SNI Nginx stream gate.
- KH: Smite Foreign Node, FRPC, optional Docker Sanaei; one 443 HTTPS Nginx vhost with restricted Smite control + Sanaei paths.
- Provider-independent goal: no requirement for Hetzner Private Network, EasyTier or Backhaul in Standard FRP mode.
- Preserve the original Private Network Wizard as a separately selectable workflow.

## Agreed two-server rebuild rehearsal (user proposal, October 11, 2026)

- **Before rebuild:** take and verify separate provider snapshots of **both** IR and KH in their known-good state. Record the exact snapshot IDs and server IDs. Retain an additional off-server export of Smite SQLite/data, Sanaei Docker database/config, Let's Encrypt, U-OPTI settings, FRP parameters and necessary SSH recovery credentials; protect sensitive backups. Provider snapshots are usually filesystem-level rather than synchronized database/network snapshots.
- **No automatic rebuild:** the user will initiate provider Rebuild actions only after explicitly confirming each backup and after the image compatibility preflight is resolved. Both hosts will be unavailable during rebuild/testing, and existing working tunnels will be interrupted. Confirm console and SSH recovery first; rebuilt SSH host keys change.
- **Test code, not production main:** install U-OPTI from a pinned **test branch or commit** on each fresh Ubuntu host. `install.sh` honors `U_OPTI_BRANCH`; all subsequent menu invocations must use the same branch selection so updates don't accidentally download `main`. Record a commit SHA before the rehearsal; test changes stay on PR #16.
- **One step at a time, explicit host:** follow the existing Wizard order, keep original Private Network untouched. Start with IR base/Panel and its HTTPS gateway, then KH Foreign Node and its gateway, then same-domain Docker Sanaei and finally managed FRP TLS/SNI tunnels. IR FRPS listener port is distinct from the KH-to-IR public 443 gateway; don't open previously blocked FRP ports.
- **At each failure:** capture logs, fix the test branch only, let CI complete, re-run the failed step on the rebuilt test system, and confirm the earlier successful steps still work. Preserve snapshots throughout.
- **Final gate:** re-test ACME dry run, all shared host routes, FRP reconnect/reboot behavior, Repair, backup/restore, and security allowlists. Only after approval and CI/end-to-end success should the PR be merged into `main` and released.
