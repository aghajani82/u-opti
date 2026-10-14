# Backhaul Sidecar — opt-in IR→KH pairing over trusted SSH (experimental)

**Status:** draft PR #18, test hosts only. This feature removes manual IR token download, KH upload, chmod and checksum comparison **when pre-existing authenticated SSH trust is configured**. It is **not** a production installer or an unattended way to provision SSH keys.

## What changes

On a **fresh, validated IR test host**, choose:

```text
U-OPTI → Smite Management → Tunnel Management → Backhaul
→ Experimental setup & recovery tools
→ 1) Pair IR/KH token over already trusted SSH (test hosts)
```

Choose **KH SSH DNS hostname** (e.g., `kh.kolbe1.ir`) and SSH port (default 22), confirm `PAIR-KH-TEST-HOST`. The wizard invokes `smite-backhaul-sidecar-ssh-pair.py --send-ir`.

- Checks root, known Smite `panel-iran`/standard mode, fresh IR host/listener state and safe private token directory. **Any active/partial independent Sidecar is a HOLD**.
- If no valid IR token exists, securely creates one using the existing root-only token helper. Never overwrites an existing token.
- Connects as **root** to KH using existing **public-key-only, batch-mode SSH** with **StrictHostKeyChecking=yes**, `/root/.ssh/known_hosts` as the pinned trust store, disabled agent forwarding, no password auth and a bounded timeout. The host/port are strictly validated; client SSH config is bypassed to prevent unsafe overrides.
- Sends the token **only through SSH stdin** to a fixed receiver command on the KH side; no token, password, hash, file content or private path goes into shell arguments, GitHub, console output or SSH verbose logs.
- KH receiver checks root, `SMITE_ROLE=foreign`, `SMITE_CONNECTION_MODE=standard`, safe /etc ancestors, fresh-host preflight, token syntax, secure directory ownership/modes and no overwrites. Creates root-owned `0600` token file using exclusive no-follow creation and fsync.
- If KH already has the **identical valid** token, returns an idempotent **no-change match**. If KH has a different, unsafe or symlinked file, aborts without overwrite.
- IR accepts **only two exact fixed success responses**, never echoes arbitrary SSH or remote stdout/stderr. If SSH trust/authentication, role, freshness or token check fails, responds **HOLD**. If a safe IR token was freshly generated before a failed SSH connection, that private token may remain for a later retry: no shared token is printed or invalidated.
- Neither send nor receive starts Sidecar, reloads Nginx or changes FRP/Smite/Xray, SSH daemon/firewall/authorized_keys or existing working tunnel files.

## One-time SSH prerequisite

**The hard part still needs user approval:** KH's **SSH host public key fingerprint must be independently verified** by the operator (e.g., using provider console/known inventory) and securely present in IR root's `known_hosts`; a trusted key usable by IR must already be authorized for KH's root SSH login. The wizard will **not** use `ssh-keyscan` as a trust decision, `StrictHostKeyChecking=no`, password auth, or auto-modify `authorized_keys`. Do not paste root private SSH keys, shared Backhaul tokens or unknown host fingerprints into chat.

If you connect to both hosts **only from Bitvise/Windows** and IR cannot key-authenticate to KH, this automation will refuse. Use your existing authenticated SFTP transfer for that first setup, or separately establish a restricted, reviewed trust path; **do not change SSH security policy just to make the wizard work**.

The KH machine must have installed the **same experimental U-OPTI branch** with the receiver helper before the IR push. For first-time preparation, provision/check KH's local Xray Backhaul test inbound and expected Smite/Nginx/FRP baseline before pairing; the receiver intentionally applies the existing `fresh-host` read-only gate.

## CLI example (IR only, fresh test host)

```bash
python3 -B /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-ssh-pair.py \
  --send-ir --kh-host kh.kolbe1.ir --ssh-port 22 \
  --confirm PAIR-KH-TEST-HOST
```

This example is **not intended for the two existing working IR and KH hosts**, where the Sidecars are already installed; their existing tokens must remain unchanged.

On KH, the menu's pairing option runs the existing private token verification **read-only**. The receiver action `--receive-kh --confirm RECEIVE-KH-PAIRING` is only for the authenticated SSH stdin stream, not for typing token characters into a console.

## Tests and follow-up

- Hermetic `tests/test-smite-backhaul-sidecar-ssh-pair.py` checks both roles and modes, protected SSH argument construction, key-only + strict-host-key settings, no secret in argv/stdout, SSH exact-ack handling, safe 0600 token creation, idempotent equality, refusal to overwrite and rejection of invalid roles/streams.
- CI and package-closure tests confirm the new helper is available after U-OPTI install/update, and updated navigation retains the working FRP wizard and existing independent Backhaul trial gates.
- **Not tested here:** actual IR→KH SSH provisioning, real host-key fingerprint enrollment, real SSH authentication or end-to-end XHTTP, Sidecar rollback/reinstall, Nginx denial bypass, or any production installation. These still require separate supervised host testing.
- Future simplification: reduce the remaining separate staging/installation path prompts *after* safe Rollback and recovery qualification; do not bypass the trial approval marker.

**Continuation:** `docs/SMITE-BACKHAUL-2026-10-14-FIELD-VALIDATION.md`, `docs/SMITE-BACKHAUL-GUIDED-OFFLINE-PREP.md`, and this file are the durable handoff. PR remains draft; no `main` merge.
