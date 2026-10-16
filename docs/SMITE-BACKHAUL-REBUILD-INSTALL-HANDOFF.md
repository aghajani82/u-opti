# U-OPTI experimental Backhaul: reproducible rebuild install handoff (2026-10-14)

**Never confuse this with production `main`.** Install source: `aghajani82/u-opti`, `feature/smite-standard-backhaul`, draft PR #18. Reviewed feature-branch head at handoff: `dc4a73b733caf97a4644eecfe95dafff752cc8ac`; CI run [38602814672](https://github.com/aghajani82/u-opti/actions/runs/38602814672) passed all seven jobs. The head may advance later; record the new SHA during a new test.

## Mandatory pre-rebuild gate (operator-performed)

Do not start destructive Hetzner Rebuild until the user has verified **separate recoverable snapshots of the exact IR/KH servers AND actual Hetzner Web Console/Rescue access to both**, expected SSH key/fingerprint changes, DNS/certificates/credentials, and an out-of-band route if VPN goes down. Keep any unrelated production VPS untouched. Rebuild one experimental VPS at a time. Prior successful Backhaul and FRP after reboot is documented in `SMITE-BACKHAUL-2026-10-14-FIELD-VALIDATION.md`; it does NOT certify the new one-flow installer on clean real hosts.

## U-OPTI install command — fresh Ubuntu test VPS (IR and KH separately)

Run from **root's own Bitvise terminal on each rebuilt test VPS**, not on Windows PowerShell:

```bash
apt-get update
apt-get install -y curl ca-certificates
curl -fL --retry 3 \
  https://raw.githubusercontent.com/aghajani82/u-opti/feature/smite-standard-backhaul/install.sh \
  -o /root/u-opti-install.sh
U_OPTI_BRANCH=feature/smite-standard-backhaul bash /root/u-opti-install.sh
```

The environment variable is **important**: without it, `install.sh` defaults to `main` even if the installer file was downloaded from the feature branch. The installer stores `/usr/local/lib/u-opti/INSTALL_REF` to persist the branch for later `Update U-OPTI` actions.

After installation, confirm the source and feature files, without changing server configuration:

```bash
cat /usr/local/lib/u-opti/INSTALL_REF
test -s /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-guided-trial.py && echo GUIDED_TRIAL_PRESENT
test -s /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-paste-pair.py && echo BITVISE_PAIR_PRESENT
```

Expected install ref: `feature/smite-standard-backhaul`. In U-OPTI, `Docker Management → Smite Management → Tunnel Management → Backhaul`. **Install U-OPTI first; do not attempt Sidecar pairing or installation until the required Smite Standard Mode/Nginx/FRP and KH Xray inbound are in place.**

## Backhaul test run sequence

1. IR: build valid Smite Standard Mode IR + Nginx 443/TLS + locally bound FRP baseline. KH: build valid Smite Standard Mode foreign + Nginx/Sanaei Xray baseline including a separate `127.0.0.1:56053` Backhaul VLESS/XHTTP inbound. Confirm each baseline read-only before Sidecar.
2. On each host, open `Tunnel Management → 1 Backhaul`; choose **4** for two-terminal Bitvise pairing: **IR** shows a long-lived private shared token on interactive terminal after explicit confirmation; **KH** accepts the pasted token in no-echo input. Never share or store the token in chat/Notepad/screenshots.
3. Next choose **5 Experimental setup & recovery → 1 Guided test install** on each host; it handles both private stage folders and admission with no manual `/tmp` typing. A separate root-owned disposable-host approval marker, verified snapshots/console and exact role-specific confirmation are still mandatory. A tested backup and marker are not supplied by the wizard.
4. Read-only status, end-to-end authenticated client VLESS/XHTTP Backhaul, old FRP, KH public numeric 13080 denial, and then IR/KH **sequential** reboot checks. Distinguish HTTP probes from real traffic.
5. Record failures and HOLD outputs before any retries. Rollback + clean reinstall is **not** field-qualified; do not force it just because CI passed.

## High-signal outputs to share WITHOUT secrets

After any issue, supply U-OPTI menu text, exact stage/error code, read-only trial status and `nginx -t` result, and role-labeled container/listening-port summaries. **Redact passwords, pairing token, UUID, private TOML/keys and public IPs if unnecessary.** The two-host pilot evidence remains in prior GitHub docs.

**Release state:** all changes are in feature branch/PR #18 (Draft); `main` is unchanged. **Automation cannot verify Hetzner snapshots, provider console availability or external client connectivity.**
