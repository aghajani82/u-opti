# U-OPTI — Two-Server Backhaul Rebuild Test Runbook (DRAFT)

**Purpose:** Run the first real from-scratch test of U-OPTI's independent Backhaul
0.7.2 wizard, without renting additional VPS instances.

## Fixed scope

- **IR** = existing experimental Iran server. It currently hosts the public
  TLS 443 gateway, Nginx, Smite panel, FRP and independent Backhaul server.
- **KH** = existing experimental foreign server. It currently hosts Xray,
  Nginx, Smite node, FRP and independent Backhaul client.
- **Third active production server = EXCLUDED.** No installer, SSH, certbot,
  DNS or Hetzner action is permitted against it as part of this trial.
- Production `main` is not changed. Test only the separately reviewed
  `feature/smite-standard-backhaul` branch (PR #18).
- A Hetzner snapshot is a **restore option, not validation** that nothing
  can go wrong. Provider restore access and remote credentials must be
  checked by the operator before any destructive Rebuild.

## Gates to be completed BEFORE any Rebuild

1. Verify a separate recent Hetzner snapshot exists **for each VPS** and
   confirm the restoration procedure is accessible under the current account.
   Do not assume that the snapshot includes DNS configuration or other
   provider-side settings; keep those recorded separately.
2. Verify Hetzner console/rescue access, SSH client credentials and an
   independent way to access each host while the VPN is down. SSH
   host fingerprints may change after a rebuild.
3. Record which domains point to the two experimental servers, current
   server-side certificates, renewal method, host firewall/provider
   firewall policy and basic Smite/Xray versions. Never publish private
   keys, private config bundles, tokens or VLESS UUIDs.
4. Explicitly accept downtime: the working test tunnels will stop during
   the rebuild. Any change after the snapshots may be lost on restore.
5. Run the local **read-only** audit, separately:

   **On IR only:**

   ```bash
   bash modules/smite-backhaul-rebuild-gate.sh --role ir --phase before-rebuild
   ```

   **On KH only:**

   ```bash
   bash modules/smite-backhaul-rebuild-gate.sh --role kh --phase before-rebuild
   ```

   These commands require a reviewed checkout/copy of the experimental
   module and its readiness dependency. Passing results do **NOT**
   verify provider snapshots or authorize a Rebuild.
6. Finish GitHub CI, manual code review, transaction/recovery checks and
   operator approval before issuing any Rebuild command.

## Rebuild #1 — clean installation trial, on the SAME two VPS

Never rebuild both machines at once. Operator explicitly confirms each
step after inspecting the output. **Do not start until the trial installer
has passed all gates.**

### IR first

1. Reconfirm IR snapshot, service identity and Hetzner console.
2. Rebuild IR to the chosen supported Ubuntu version. Expect VPN outage.
3. Install U-OPTI from a **pinned, reviewed test commit**, not the main
   release branch. Finish SSH, Nginx, Docker and Smite panel baseline.
4. Restore/configure the real IR HTTPS domain/certificate, Nginx
   backend, FRP controller and port 443 SNI route. Validate with
   `nginx -t`; inspect baseline before continuing.
5. **On IR only**, validate:

   ```bash
   bash modules/smite-backhaul-rebuild-gate.sh --role ir --phase fresh-baseline
   ```

6. Generate a private shared token on IR, transfer to KH later using a
   trusted encrypted channel, and generate the role-specific Sidecar
   candidate + separate Nginx plan. The token is never pasted in chat.
7. Run paired admission/readiness and inspect every proposed file.
   Only then use a separately authorized trial installer. Confirm
   listener ownership and that the website/Smite/FRP remain reachable.

### KH second

1. Reconfirm KH snapshot and console. Rebuild KH separately.
2. Install the same U-OPTI pinned test commit, Docker, Nginx, Smite
   node, Xray and its actual VLESS/XHTTP inbound on localhost 56053.
3. Confirm the HTTPS domain, trusted IR certificate and IR public 443
   can be reached from KH **without disabling TLS verification**.
4. **On KH only**, validate:

   ```bash
   bash modules/smite-backhaul-rebuild-gate.sh --role kh --phase fresh-baseline
   ```

5. Generate the KH role candidate using the same private token.
   The KH Nginx plan must block public forwarding to port 13080,
   including leading-zero numeric URLs, ahead of the numeric regex.
6. Run the admission gate; check the loopback-only bridge, Nginx
   TLS validation and no conflict with Xray, FRP or Smite.
7. Use the explicitly authorized experimental installer; confirm
   local port 13080, the named Sidecar and the verified TLS bridge.

### End-to-end acceptance after both hosts are installed

- FRP and Smite still operate through their previous paths.
- Nginx remains valid; website HTTPS returns a successful response.
- Both independent Sidecar containers have correct pinned image,
  host networking and `unless-stopped` restart policy.
- IR binds 3080 and 56053 only to loopback.
- KH Nginx bridge binds 13080 only to loopback; Xray binds 56053
  only to loopback.
- An HTTP 401 from Backhaul `/channel` and an HTTP 400 from a
  bare XHTTP GET are **not** proof of working VPN traffic.
- Authenticate with the real VLESS/XHTTP client on Windows or
  Android and browse a site through IR -> KH. Confirm on both ends.
- Reboot **KH alone**; repeat complete health and real-client tests.
  Reboot **IR alone** only after KH passes; repeat tests.
- Record no secrets in CI artifacts, terminal screenshots or support logs.

## Rebuild #2 — destructive recovery trial (only if #1 passed)

Use the same two VPS; no further VPS purchase is necessary.

1. Take fresh snapshots of the **verified new installation** (optional
   additional restore point) while maintaining the original snapshots.
2. Only on an experimental VPS, simulate failures at supported
   checkpoints (invalid Nginx candidate, Docker image unavailable,
   blocked bind, wrong token). Never inject failures into the
   production third server.
3. Verify rollback restores exact Nginx contents and ownership/mode,
   removes only installer-owned Sidecar files/containers and preserves
   FRP/Smite/Xray. Verify a successful real client after recovery.
4. Restore the selected snapshot only when explicitly approved.
5. If ANY component is unknown or rollback has foreign drift, stop
   and diagnose. Do not force-delete another service's resources.

## Known limitations before final release

- The CLI-enabled `smite-backhaul-sidecar-live-trial.py` is **experimental**
  and not yet automatically installed into the released U-OPTI menu.
- The role-specific Nginx planner currently expects the tested
  file layout, including a specific KH vhost path; it is not a generic
  installer for arbitrary domains/vhosts.
- Certificate/DNS provisioning and creating the base Smite/Xray
  inbounds are prerequisite steps, not currently automated by the
  Backhaul Sidecar installer.
- Client-side, authenticated full-path VLESS verification is
  required outside CI. A green GitHub Actions run cannot prove the
  real Iranian network path.
- The test-host installer currently depends on pre-existing private
  token/candidate folders; secure automated IR-to-KH pairing for
  a beginner is a separate feature.
- Provider snapshots must be verified by the operator; their contents
  and restoration reliability cannot be inferred from OS inspection.

**Release decision:** do not merge PR #18 to `main` until at least
one complete two-server manual trial (fresh install, end-to-end client,
individual reboot, failure/rollback, clean repeat) has been documented.
