# Clean-RC Stage15 KH: signed pairing with the existing IR Panel

Scope: disposable Ubuntu 24.04 amd64 hosts only. No production release, no live
host access, no image rebuild or IR upgrade is performed by this change. The
operator reports `node-ir` Connected at `https://02ir.kolbe1.ir`.

## Source and image evidence

U-OPTI base: `e13f2735aec41047414b2f3b7937c610ac013e46` (PR #64).
Smite main reviewed: `536f723d088540cbec5064037532d48c1579e554`.
The exact Stage15 build source is `4e16633a304db6c03f7f2911cc7d77213b0c4ec1`.
Its diff to the reviewed Smite main changes only the delivery-board document;
there is no executable-code difference.

The independent successful [Stage15 build](https://github.com/aghajani82/Smite/actions/runs/40461876836),
[job 122048191494](https://github.com/aghajani82/Smite/actions/runs/40461876836/job/122048191494),
records these Docker image IDs (not interchangeable with OCI release digests):

| Role | Local tag | Immutable image ID |
| --- | --- | --- |
| Existing IR Panel | `smite-panel:stage15-local` | `sha256:51f7e45e06e8cc59f4f04972090962b9c8d6db8aad2ec1591fc5ede0da112ae9` |
| IR/KH Node | `smite-node:stage15-local` | `sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991` |

Bundle artifact ID: `12714389112`; the bundle is temporary, so preserve an
independently verified copy before GitHub retention expires. Do not rebuild and
assume the rebuilt image has the same ID.

- ZIP SHA256: `2bda0c80aa77ce6fa6bd1af0a4ed0d8fccfad670915dfd2f56a6120b08d19a71`
- `stage15-images.json` SHA256: `fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a`
- Both Panel and Node archives are required by the existing pair verifier, even
  though KH loads only the Node image.

The Stage15 Panel's `signed_agent_transport.py` already supports
`gateway_control_url`, exact separately approved HTTPS/443 origins, verified TLS,
no redirects/proxy-environment inheritance, and HMAC over the original Node
`/api/agent/*` path. `NodeClient` uses the protected origin record rather than
self-reported metadata. The Node already supports signed HTTPS registration,
strict Agent HMAC, durable Replay and paused rollback.

**No IR Panel image upgrade is needed for this KH Signed Pairing path.** The old
RC.2-only Panel admission and RC.1-only default KH image gate were stale. This
change adds the exact proven Stage15 lane, checks BOTH running and tagged image
IDs, retains the live Panel capability check, and checks KH effective Compose,
health and verified TLS before activation. Unknown images still HOLD. The
separately opted-in RC.2 lane remains frozen and cannot accept Stage15 as a
substitute. This is experimental provenance, not signed production attestation.

## Installation order (no manual Compose editing)

**Foreign Node → Sanaei install and read-only attachment → KH Gateway → reserve
KH on IR → approve its Origin on IR → redeem on KH → activate signed KH.**

Sanaei attachment and Gateway setup recreate the base Node while it is still
paused. Do not postpone them until after Pairing. Sanaei now refuses staged
identity, signed runtime, ambiguous runtime auth or non-paused configuration.
Gateway already refuses a staged identity. Neither path silently removes a
signed runtime overlay.

### KH: fresh U-OPTI and bundle

Choose a real KH DNS hostname pointing directly to KH; it is not supplied in the
request. The existing Panel hostname is `02ir.kolbe1.ir`. Keep public 8000/8888
blocked; Nginx owns HTTPS/443 and ACME uses 80. Do not use the old Stable wizard.

After this PR merges, substitute its final merge SHA below. Run only on KH when
the operator starts the separate live test. The following is a source install,
not a server rebuild:

```bash
# KH ONLY — replace with this PR's final merged commit
UOPTI_SHA='<MERGED_COMMIT_SHA>'
curl -fSL --proto '=https' "https://raw.githubusercontent.com/aghajani82/u-opti/$UOPTI_SHA/install.sh" -o /tmp/u-opti-stage15-install.sh
U_OPTI_BRANCH="$UOPTI_SHA" bash /tmp/u-opti-stage15-install.sh
```

If U-OPTI is already installed, instead run `U_OPTI_BRANCH="$UOPTI_SHA" u-opti`
and select Update U-OPTI. Do not run a second Smite installation over existing
state. Exit the menu before the next command.

Copy the verified Stage15 ZIP to KH by the operator's existing transfer method,
verify its ZIP SHA above, and extract its three files into
`/opt/smite-stage15-bundle`. Do not extract an unverified or replacement ZIP.
Then open the actual Clean-RC wizard:

```bash
# KH ONLY
SMITE_RC_BUNDLE_DIR=/opt/smite-stage15-bundle \
SMITE_RC_SOURCE_SHA=4e16633a304db6c03f7f2911cc7d77213b0c4ec1 \
SMITE_RC_MANIFEST_SHA256=fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a \
u-opti --smite-clean-rc
```

1. Select **2) Install Foreign Node**. Panel domain: `02ir.kolbe1.ir`; Foreign
   domain: the real KH hostname; Node name: `node-kh`. Standard is selected
   automatically. Require Healthy and paused/strict; this is not Connected yet.
2. Select **4) Install Sanaei 3x-UI on Foreign Node**. Use the existing U-OPTI
   installer. If it returns to the main menu, reopen the exact Clean-RC command
   above and select 4 again to attach the chosen instance database read-only.
   The mount exposes sanitized inbound inventory, not write access to Sanaei.
3. Select **6) Configure Foreign HTTPS/443 Gateway**. Confirm the real IR source
   IPv4 for the allow-list (not a CDN address). The wizard creates the random
   `/smite-node/<prefix>` control path, certificate, Nginx route and Node control
   metadata. Retain the displayed exact Control URL. Do not invent the prefix.
   Require `FOREIGN_RC_GATEWAY_TRANSPORT=READY_ROOT_ONLY` and
   `FOREIGN_RC_NODE_RUNTIME=PAUSED_STRICT`.

### IR: approve only after separate operator consent

Updating U-OPTI source on IR is needed for the new admission gate; no Panel image
replacement, admin migration, DB restore or Node re-pair is needed. Preserve the
existing secure backup/snapshot and install the same reviewed U-OPTI commit
through Update U-OPTI only after explicit operator approval. Leave `node-ir` and
its identity/replay files intact. Do not use the old RC.0→RC.1 upgrade option.

In Panel → Foreign Nodes, reserve **node-kh by name** in signed mode. Record the
new UUID. On IR run `u-opti --smite-pairing`, choose **8) Approve foreign KH Gateway
origin**, confirm `APPROVE-KH-PIN`, and enter that UUID, `node-kh`, and the exact KH
Control URL. It checks TLS, pending reservation and Panel implementation, then
adds only the protected KH origin record. Existing IR origin entries are kept;
failed verification restores the previous origin file. No Panel restart occurs.

After approval, create a fresh short-lived one-use code for that reserved Node.
Do not use the old IP/API-port registration form or reuse the IR identity.

### KH: redeem and activate from the wizard

Run `u-opti --smite-pairing`:

1. **3) Redeem one-time pairing code**; enter the Panel hostname, reserved UUID
   and code through the interactive prompts (never as command-line arguments).
   Confirm STAGED identity. Do not configure Gateway/Sanaei after this point.
2. **7) Activate signed KH Node runtime**, confirm `ACTIVATE-KH-SIGNED-NODE`.
   Replay is provisioned by the pinned offline image; the strict security
   candidate is applied without manual Compose edits.
3. Require all markers: `KH_SIGNED_NODE_RUNTIME=ACTIVE_FIELD_TRIAL`,
   `KH_LOCAL_HMAC_REPLAY=PASS`, `KH_TO_PANEL_SIGNED_CHECKIN_AND_GATEWAY=PASS`,
   `PANEL_TO_KH_SIGNED_HMAC=PASS`, plus `node-kh` Connected in Panel.

A failure must HOLD and verify paused rollback. Never delete Replay/identity to
force a retry. If rollback is reported unverified, stop. This source/CI result is
not evidence that live KH signed activation or client traffic has passed.

## FRP and XHTTP: exact automation boundary and remaining blocker

**KH pairing readiness is not FRP deployment readiness.** Current main still
prints `Install FRP (not enabled yet)` in `smite-managed-frp-menu.sh` and refuses
real-host installation. Clean-RC intentionally skips engine enrollment. The
Stage15 Node contains FRP binaries, but managed mode does not authorize arbitrary
bundled binaries merely because they exist. Independent engine provenance and
managed enrollment must be admitted first.

**Stage15 read-only admission (new):** after signed KH activation, run
`python3 -B /usr/local/lib/u-opti/modules/smite-managed-frp-control.py stage15`
on **each** disposable node host, or choose Independent FRP > 4 in U-OPTI.
The bounded gate verifies the exact local Stage15 Node image ID, the signed
strict runtime and active Compose overlay, the 127.0.0.1:8888 listener command,
no published Node ports, expected identity/Replay mounts, and both bundled
FRP v0.71.0 executable versions. It does **not** read secrets, spend a signed
nonce, create a tunnel, attest the OCI supply chain, or authorize FRP install.
Expected success still reports `HOST_FRP_INSTALL=HOLD` and
`SIGNED_HMAC_REPLAY_PROOF=NOT_QUERIED`. A `HOLD` is a reason to stop,
never an invitation to override image IDs or enable the WSS flag.

Additionally, `SMITE_FRP_STANDARD_WSS=1` is not set by the Clean-RC installer.
The existing shared-child implementation requires it; without it, a shared child
fails before mutation. Historical RC.2 WSS activation helpers pin different
images and are **not** a safe command for this Stage15 pair. Do not substitute
IDs or set the flag manually. A reviewed Stage15-compatible engine/WSS activation
transaction is a remaining prerequisite, not implemented by this pairing fix.
Do not expose raw 7000 or activate a legacy tunnel as a workaround.

Once that prerequisite is separately implemented/tested and explicitly approved,
the existing intended UI sequence is:

1. In Sanaei create a **new** enabled VLESS/XHTTP inbound on `127.0.0.1:P`,
   security none, mode auto, with a chosen unique Path. Operator chooses the
   free port, path and client credentials. Nothing here creates an inbound.
2. In Smite → Tunnels create the first FRP TCP owner for `node-ir`/`node-kh`,
   control port 7000 internally, WSS/443 externally, loopback proxy binding.
   Require authenticated live owner proof. Do not create a second FRPS owner.
3. For an additional port, choose that active owner in **FRPS owner / add port**,
   select exactly one new port matching the KH inbound, and wait for the child
   and unique lease to become active. Current XHTTP UI registration targets
   **shared children**, not the first owner row. Plan a distinct first-owner
   test port if exercising a new child; never duplicate an occupied owner port.
4. Prepare the IR-owned Nginx Bridge separately with the guarded helper, after
   explicit IR approval. Its `plan` is read-only; `apply` is interactive and
   maintains a backup/journal and nginx/TLS checks. This PR fixes admission of
   the empty root:root 0755 directory precreated by Clean-RC. It does not admit
   existing route files or unknown bridges; rollback preserves that directory.

   ```bash
   # IR ONLY — plan is read-only; apply requires separate approval
   python3 -B /usr/local/lib/u-opti/modules/smite-rc5-xhttp-bridge-install.py plan
   UOPTI_RC5_IR_XHTTP_BRIDGE_TRIAL=YES \
     python3 -B /usr/local/lib/u-opti/modules/smite-rc5-xhttp-bridge-install.py apply
   ```

5. Use **XHTTP** on the active child. Panel reads port/path from signed KH
   inventory, verifies the live IR owner and lease, and sends a signed intent.
   The root Broker still requires an independent per-child grant. When the UI
   reports `ROOT_OPERATOR_GRANT_REQUIRED`, independently review its facts on IR:

   ```bash
   # IR ONLY — interactive, separately approved per child
   python3 -B /usr/local/lib/u-opti/modules/smite-rc5-xhttp-broker-provision.py \
     --approve-grant --confirm-local-root
   ```

   Enter the actual Node/owner/child/lease IDs, port and path shown by the verified
   records; never invent them or copy an incoming request as its own authority.
   Root evidence is operator-asserted; autonomous remote proof retrieval is not
   implemented. Retry from Panel only after grant success and known state.
6. After route success, create a new client using `02ir.kolbe1.ir:443`, TLS/SNI
   for that hostname, and the exact KH VLESS credentials and XHTTP Path. Validate
   real traffic, then separately approved reboot/rollback tests.

| Step | Current behavior |
| --- | --- |
| Foreign install, paused/strict, local bind | Wizard, automated after confirmation |
| Sanaei install and read-only DB mount | Wizard; instance/operator selection, revisit option 4 |
| KH Gateway path/certificate/allow-list | Wizard; hostname/source-IP confirmation required |
| Reservation, code, Origin approval, activation | Explicit Panel/U-OPTI actions; no automatic pairing |
| FRP engine enrollment + WSS on Stage15 | **Blocked: reviewed activation integration remains** |
| Sanaei inbound port/Path/client | Manual in Sanaei; no automatic inbound creation |
| Owner/child selection | Manual UI; signed proof/lease checks automated |
| Read KH port/Path, build signed route intent | Automated after explicit UI selection |
| IR Bridge and per-child TrustedGrant | Separate local-root approval; not automatic |
| Nginx route transaction | Broker after all gates; syntax/rollback checks automated |
| Client and two-host traffic/reboot acceptance | Still a live field test, not established by CI |

No IR/KH/Grandoptical mutation was made. No production readiness is claimed.
