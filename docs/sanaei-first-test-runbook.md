# Experimental Sanaei-first Standard Smite + FRP + Backhaul runbook

**Branch:** `feature/sanaei-first-dual-profile-20261017` (Draft PR #26). **Do not use on production.** Main remains unchanged. Existing working IR/KH servers should be snapshotted and preserved; restore CLEAN TEST snapshots before the installation trial.

## Invariants

- Both hosts have distinct logical roles: IR = Panel+Iran Node+HTTPS entry, KH = Foreign Node+3x-UI exit.
- KH Sanaei can be installed **before** Smite. Smite Foreign Node **cannot** register before IR Smite Panel/HTTPS is available.
- FRP and Backhaul Xray inbounds have **two distinct loopback ports** and **non-overlapping XHTTP base Paths**. The same four non-secret values are recorded locally on BOTH hosts.
- A Profile First plan is **only** `/etc/u-opti/tunnels/profile-first.json` (root-only). It never creates Xray inbounds, certificates, routes, tunnels, Docker containers, tokens, or user credentials. A saved plan must not be mistaken for applied routing.
- FRP route activation still requires a Smite UI FRP TCP tunnel. Backhaul Sidecar deployment requires Smite/Nginx baseline, private pairing, disposable TEST VPS approval, trial journal and explicit user consent.
- Never publish the long-lived IR Backhaul code, private TOML, or Xray UUID.

## Install on a fresh test host (run once separately on IR and KH)

```bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/feature/sanaei-first-dual-profile-20261017/install.sh -o /tmp/u-opti-test-installer.sh
U_OPTI_BRANCH=feature/sanaei-first-dual-profile-20261017 bash /tmp/u-opti-test-installer.sh
```

Afterwards, `cat /usr/local/lib/u-opti/INSTALL_REF` must print the feature branch. `VERSION` alone is insufficient: it may equal main's version number.

## Workflow, minimizing cross-host switches

1. **KH first:** Install Docker and Sanaei 3x-UI from U-OPTI; finish its Nginx/SSL. In the 3x-UI panel manually create **two** VLESS/XHTTP inbounds bound to `127.0.0.1`, for example FRP `13914` + `/13914/shop`, Backhaul `58408` + `/58408/ooo`. Use your own distinct values. Do not create FRP or Backhaul tunnels yet.
2. **KH:** U-OPTI > Docker Management > Smite Management > Tunnel Management > **5) PROFILE FIRST**. Set and save both ports+Paths. Confirm with option 2. Note/copy only the FOUR non-secret values.
3. **IR:** Install Docker, then U-OPTI > Smite Management > Tunnel Management > FRP > **START HERE** to install Smite Panel and Iran Node **Standard** and configure IR HTTPS/443 gateway. On IR use PROFILE FIRST option 5 to save the SAME four values from KH.
4. **KH:** Now Smite Foreign Node registration can reach IR Panel HTTPS. Use FRP START HERE (Standard Foreign + KH HTTPS control gateway). Existing Sanaei 3x-UI must be **preserved**, not reinstalled.
5. **IR:** After PROFILE FIRST is saved, create/apply the matching FRP TCP tunnel in Smite UI (IR server/KH client). The guarded FRP sync timer reads the trusted plan and automatically publishes the correct path **only after Apply**; it must never fall back to `/PORT/web` for that planned port. Run FRP option 3 to verify the HTTPS route. FRP option 2 is still available for explicit overrides or recovery, but should not be required for a fresh profile-first install.
6. **IR:** Backhaul START HERE; accept only on a disposable host after snapshots and console access. When asked, choose the **saved Backhaul** port+Path. Install independent IR Sidecar. Display IR pairing code only with local interactive consent, and copy it privately.
7. **KH:** Backhaul START HERE; KH Step 1 is only a hidden `y` consent, Step 2 is a distinct **hidden code entry**. Choose saved Backhaul profile; install KH Sidecar. Never type the long-lived secret at Step 1.
8. **Both:** Run read-only Backhaul audits; verify FRP route independently, test two **real** VLESS clients, and reboot IR and KH **one at a time**, checking persistence after each reboot.

## Regression confirmed in fresh VPS trial

Previously, saving FRP port `42175` and XHTTP Path `/42175/windows64`
in PROFILE FIRST left Nginx at legacy `/42175/web` after Smite FRP TCP
Apply, even though the loopback FRP tunnel already reached Xray on KH.
Only a separate FRP option 2 invocation fixed the route.
The fixed Nginx renderer now checks the trusted local Profile First plan
as a fallback for the **matching applied FRP server port**. Explicit FRP
path registry entries continue to take priority and users without a
Profile First plan retain legacy `/PORT/web` defaults. The renderer
rejects unsafe plan files, overlapping Sidecar routes and unsafe path
prefixes; existing Nginx rollback protects the active gateway on error.
A saved plan itself must never create a tunnel or route.

## Acceptance criteria before main merge

- Full clean install with no second/duplicate installation on either host.
- Both inbounds on KH and both public IR client profiles connect without port/path collisions.
- Error output distinguishes wrong consent, missing approval, missing installed state and installed-but-unverified final cleanup; no secret displayed.
- Nginx TLS/443 site and Smite FRP route survived Sidecar activation.
- Both survive sequential reboots. Rollback/snapshot accessible.
- CI alone is not an E2E VPS success claim.
