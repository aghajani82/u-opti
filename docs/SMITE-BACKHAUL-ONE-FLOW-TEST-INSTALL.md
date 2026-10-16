# Backhaul Sidecar — one-flow guarded installation for rebuilt TEST VPS (2026-10-14)

**Repository:** aghajani82/u-opti | **Branch:** feature/smite-standard-backhaul | **Draft PR:** #18

This handoff documents the improved beginner workflow. It is still an **EXPERIMENTAL disposable-test-host installer**; it does not represent production approval or completion of live rollback/reinstall qualification.

## Goal and current proven baseline

An earlier two-host pilot installed the independent IR and KH Backhaul Sidecars and the operator confirmed real Backhaul and existing FRP client connectivity **after sequential reboots**. That trial had manual /tmp directory generation and copy/paste. These field-tested Sidecars have **NOT** been changed by the GitHub work here.

The new `modules/smite-backhaul-sidecar-guided-trial.py` reuses the same verified trial transaction engine and paired read-only admission, but automatically prepares both **fresh private local proposals** and passes their paths to the installer without asking the operator to type the paths. Private proposal directories are then removed, and cleanup is verified before reporting local success. Exact journal and Nginx recovery backup are persisted separately under the existing trial state root.

## Simplified beginner path — separate Bitvise terminals

The operator normally opens **two Windows Bitvise sessions** (one IR and one KH), not server-to-server SSH. The intended **fresh rebuilt TEST host** order is:

1. Independently verify snapshots, accessible provider web console, and that the two VPSs are **disposable** before any rebuild. Rebuilding destroys current host data and the existing tested live configs.
2. Install/update U-OPTI **from the experiment branch**, not from `main`, on each rebuilt host. Establish the required Smite Standard Mode role: IR is `panel-iran`, KH is `foreign`.
3. Prepare the established baseline first: public HTTPS Nginx routes and valid certs, the Smite IR/KH components, existing Standard FRP and its Xray inbound, and the separate KH Xray Backhaul inbound at `127.0.0.1:56053` with VLESS/XHTTP path `/56053/www/`. The new one-flow wizard **does NOT create these baseline components, register nodes, create Xray users, or set up DNS/certificates**.
4. On a fresh IR test VPS, open `Smite Management → Tunnel Management → Backhaul → 4) Pair IR/KH with a copied code`. After explicit approval, a shared Backhaul secret is displayed on the interactive IR terminal. Treat it as a persistent credential, **not a one-time code**.
5. On the separate **KH** Bitvise terminal open the same pairing option, paste the IR value into the hidden no-echo prompt. The helper verifies root, role, a fresh host and safe ownership/modes, then creates or exactly matches the private KH token. No server-to-server SSH or SFTP transfer is required in this option. Avoid screenshots, chat, Notepad and clipboard history containing the secret.
6. On each host independently, select `Smite Management → Tunnel Management → Backhaul → 5) Experimental setup & recovery tools → 1) Guided test install`. Supply the IR HTTPS domain and KH upstream hostname **one time** on that host.
7. The wizard requires a **separately operator-created rebuilt/disposable-host approval marker** at `/root/.uopti-backhaul-rebuilt-test-host` (root-owned, mode 0600, exact approved content), available snapshot/console, the literal `REBUILT-TEST-VPS` confirmation, and a role-specific `INSTALL-IR` or `INSTALL-KH` confirmation. It will not create the marker or bypass these checks. Never invoke it on the prior active Sidecar installs.
8. Behind the scenes, the one-flow coordinator validates the true Smite IR/KH role, confirms no existing local trial journal, runs the read-only new-host baseline checks, generates private Sidecar plus Nginx proposals, reconciles both bundles, then delegates to the unchanged transactional trial installer. The underlying installer rechecks port and path ownership, Nginx and Docker, creates a durable file journal and original-vhost backup, starts only its own Sidecar, reloads Nginx, and checks local health.
9. After each host succeeds, separately verify both Sidecar container statuses and listening ports, **real authenticated Backhaul VLESS/XHTTP**, existing FRP VLESS/XHTTP, HTTPS/SNI, and denied public forwarding to KH bridge port 13080 (including leading-zero variants). A status page or unauthenticated HTTP 401/400 is insufficient evidence.
10. Reboot **only one** disposable host at a time **after ensuring console access**, then re-test both client profiles and rollback prerequisites before considering the trial successful.

### Menu summary

```text
Smite Management
  2) Tunnel Management
    1) Backhaul
      1) Status (read-only)
      2) Strict audit (read-only)
      3) Client profile
      4) IR/KH two-terminal copy/paste pairing (FRESH TEST ONLY)
      5) Experimental setup & recovery
        1) Guided test install (no manual /tmp paths; WRITES this TEST host)
        2) Fresh host check (read-only)
        3) Offline plan only
        4) Existing trial status / guarded rollback / legacy install
        5) Optional pretrusted SSH pairing
        6) Manual tools
```

## Safety limits and acceptance gates

- **Never Rebuild the existing working hosts based only on passing GitHub CI.** CI runs in synthetic runners and does not confirm restored external reachability, the specific VPS state, token pairing, or Nginx/TLS after live changes.
- The independent Sidecar remains separate from **Smite in-panel Backhaul**. Smite does not yet offer centralized creation of these Sidecar tunnels. Do not create overlapping Smite Backhaul on the same ports.
- The current test topology uses a fixed Xray port `56053`, Backhaul WS control `3080`, and KH loopback TLS bridge `13080`; arbitrary port selection, multi-tunnel Sidecar management, full FRP+Smite bootstrap and automated failover are **not implemented**.
- The separate **guarded rollback** remains available using the trial journal but has **NOT** yet been field-tested on two disposable rebooted hosts. Do not claim it proven.
- No existing FRP, Nginx, Xray, Smite, or active independent Backhaul configuration is modified by these GitHub commits alone.
- Unexpected errors may occur *after* partial activation. **Never blindly retry**; first inspect the read-only trial status and journal. Recovery will HOLD for altered ownership, unexpected third-party drift, or journal changes.
- The two-terminal pairing prints the secret on IR deliberately. Protect terminal scrollback and clipboard. It is **not** a short ephemeral one-time invitation.
- This documented workflow is the target for the user's planned **new disposable-host rebuild test after explicit approval**. Before advising rebuild, confirm the full GitHub CI is green and snapshots and provider console are available.

## Continuation and GitHub evidence

See `docs/SMITE-BACKHAUL-2026-10-14-FIELD-VALIDATION.md`, `docs/SMITE-BACKHAUL-GUIDED-OFFLINE-PREP.md`, and draft PR #18 for the earlier test observations, assumptions and pending acceptance gates.

One-flow trial synthetic tests are in `tests/test-smite-backhaul-sidecar-guided-trial.py`. All code stays on `feature/smite-standard-backhaul` until approval; no automatic merge to `main`.
