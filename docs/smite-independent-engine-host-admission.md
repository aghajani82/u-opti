# Stage: one shared READ-ONLY host admission for independent Backhaul / FRP

Date: 2026-10-19. Branch: `feature/smite-clean-fresh-install-20261018`.
Draft PR: `aghajani82/u-opti#38`.

## Operator view: one familiar option

`U-OPTI → Smite Management → Independent Engines`

- **Backhaul → 2) Review installation prerequisites**
- **FRP → 2) Review prerequisites (no ports)**

Both choices run the same reviewed `smite-managed-engine-host-admission.py`
with a different `--engine` argument. They do NOT attempt an installation,
restart Docker or ask for an Xray inbound port, path or transport.

Example reviewed command shape (for future clean test VPS only):

```bash
# TARGET: IR or KH separately — READ ONLY
python3 /usr/local/lib/u-opti/modules/smite-managed-engine-host-admission.py \
  --engine backhaul --format text
python3 /usr/local/lib/u-opti/modules/smite-managed-engine-host-admission.py \
  --engine frp --format text
```

These helpers live on the experimental Branch. They may **not yet exist**
on an older installed U-OPTI (including 0.16.7). **Do not run them on
currently working IR/KH hosts or rebuild just to install the helpers.**

## What this checks, without reading/displaying secrets

- Exact clean Core role (IR/KH), managed+strict auth flags, root-owned
  `.env` and original Node Compose layout
- `docker inspect` of the reviewed running `smite-node` only: image
  digest allowlist, host-network assumption, no published Docker ports,
  proper config bind and `smite-node-data` named persistent volume
- Strictly parsed and **never returned** persisted tunnels; any saved
  tunnel holds admission before attempting an engine change
- Engine-specific local inventory and read-only binary/mount evidence.
  Not installed, unavailable and enrolled-but-*not-signed-confirmed*
  remain distinct
- Existing independent engine: **preserve as-is**; do not uninstall,
  overwrite, auto-repair, or treat unsigned filesystem evidence as ready
- Detect changed Compose during the read-only inspection, and record
  only safe status/hold classifications; not raw Docker/.env/tokens,
  container paths, pairing keys, or engine checksum values

## Every result intentionally remains HOLD

Regardless of local preflight findings:

`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

No local read-only report can verify real cloud snapshot recovery, rescue
console, complete host crash rollback executor, signed Node replay health,
public TLS 443 or firewall exposure. Such claims are always `UNVERIFIED`.
Engine preflight can pass locally while the **overall release gate remains
closed**.

The current working U-OPTI 0.16.7 FRP+Backhaul servers are a legacy
baseline and are not eligible for the new strict managed engine installer
without a separately reviewed clean Core deployment.

## Remaining implementation before the one-time clean Rebuild

1. Human-approved snapshot/console recovery for each disposable IR/KH
   candidate, plus independent snapshot evidence (never forged in JSON).
2. A production-safe host journal/lock/executor with explicit restart
   admission, crash/reboot survival and identity/replay/tunnel preservation;
   Backhaul and FRP install/rollback must share its transaction lock.
3. Real host Node mounts + signed HMAC `ready`, back-to-`not-installed`
   rollback, and clean recovery on failure; no silent success.
4. Real 443 gateway/path/port integration, Panel pairing and Xray
   mapping, Backhaul-only then FRP independently; no mandatory tunnel
   port at engine install and no other engine changes.
5. Final pinned code/image/archive digests, green two-repo CI, explicit
   operator approval, main merges/releases, and **only then** one
   controlled clean installation with official U-OPTI command.

No production install buttons have been enabled; no modifications to
the working VPS, `main`, tag or release were made.
