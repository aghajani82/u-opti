# Stage15 console approval shortcut

Source-only UI change. No host deployment, web approval, new service/domain,
RC2 publisher change, image change, owner reapply or main merge.

## Operator flow

1. Open `u-opti` on IR and navigate to Docker Management → Smite Management.
   Keep this menu ready before requesting publication in the Panel.
2. Select the inbound in Smite and request XHTTP publication. If an independent
   root grant is missing, the existing broker stages the signed proposal.
3. Choose **G — تأیید پورت و مسیر تانل** directly in Smite Management.
   Compare the displayed tunnel ID, IR/KH node IDs, port, path, owner, lease
   and evidence hashes with current trusted IR/KH evidence and the active lease.
   Choose **1 — Approve** or **0 / Enter — Cancel**. Other answers also cancel.
4. After `ROOT_GRANT_APPROVED`, submit a **fresh** publication request in the
   Panel. Console approval does not publish, reload Nginx or restart FRP.

The original Stage15 **G** entry remains available and calls the same helper.
The new shortcut needs no Passkey modules or web-approval opt-in.

## Preserved boundary and limitations

- IR root plus interactive TTY remain required. No command-line auto-approve.
- Both signature/freshness checks remain, before display and after selection.
  Exact proposal bytes are re-read before the durable exclusive audit and grant.
  The digest remains internal to audit; it is no longer a typing exercise.
- **No TTL extension.** The Panel still issues its existing short-lived intent.
  An expired/invalid/replaced request is HOLD. Keep the menu ready first; this
  change does not solve slow manual review by accepting stale requests.
- The signed schema has **no human-readable tunnel or node name**. The console
  explicitly reports the tunnel name unavailable and displays authenticated IDs.
  Adding names from an unauthenticated API or changing the signed schema is
  deliberately outside this patch. All signed binding fields remain visible.
- This is the existing **operator-asserted independent evidence review**, not
  automatic independent attestation. A valid Panel signature alone does not
  establish that the KH inbound or lease is correct.
- Existing grants are never overwritten. Repeating the same approved proposal
  is blocked by the exclusive durable audit. Publication retains its existing
  durable nonce ledger; console review neither consumes nor resets that ledger.
- Failure after audit/grant issuance remains HOLD requiring review; no automatic
  deletion, grant replacement or retry is added.

## Signed KH Inventory dependency

Reviewed counterpart: Smite PR #41, `1f28222d80c29a9423da445c7e977cbc1867aead`.
`panel/app/xhttp_route_lifecycle.py` obtains Signed IR owner proof and Signed KH
Sanaei inventory before signing/forwarding an intent, and again for fresh
publication. Unavailable inventory produces `SIGNED_KH_INVENTORY_UNAVAILABLE`;
the selected port must be unique, enabled VLESS/XHTTP on `127.0.0.1`, with the
selected path bound into the intent. Missing/invalid inventory cannot be fixed
or bypassed by this shortcut. KH's opt-in read-only Sanaei DB mount, WAL/SHM
availability and signed Node API must already work.

No live IR/KH inventory status was inspected in this change. Repository tests
are evidence of code behavior, not proof of the deployed runtime. Existing
inventory migration remains separate and is not invoked by either G entry.

## Field trial: fourth FRP route (operator-reported, 2026-11-01)

The IR/KH field trial was performed outside CI and confirms the practical
operator path, not a signed release or general production readiness:

- KH `smite-node` reported healthy, with
  `SMITE_SANAEI_INVENTORY_ENABLED=true` and read-only Sanaei SQLite mount.
  Inventory reader returned approved XHTTP inbounds. A fourth inbound at
  port `45122` with path `/45122/store` was subsequently observed.
- IR Panel retrieved the same KH inventory through authenticated Signed
  Node GET before the fourth route was created.
- A shared FRPS child named `FRP-IR-KH-45122` was created under the
  existing `FRP-IR-KH-45121` owner. The Panel reported the child active.
- The Panel prompted for independent approval. The IR root-console
  operator used shortcut `G` with numeric confirmation and observed
  `ROOT_GRANT_APPROVED; ROUTE_NOT_CHANGED`.
- The operator submitted a **fresh** Panel XHTTP publication request and
  reported a successful real VLESS/XHTTP client connection through
  `02ir.kolbe1.ir:443`.

Source control follow-up: persist the terminal-safe English
`G) Approve FRP Port + Path (Stage15 / IR)` label and a Persian-language
in-Panel publication guide (in Smite PR #41). These UI changes do not
change signed request, lease, grant, replay or root broker contracts.

Scope and evidence limits: the above are operator-provided live results;
the helper itself does not attest the real client data plane. No new
FRPS owner, Passkey deployment, Grandoptical change, automatic retry,
production merge or image rollout is authorized by this field-trial record.

## Validation

Root-review tests cover simple approval, full signed binding display, cancellation,
EOF, invalid signature, expiry before/during review, replacement of every binding
field (even correctly re-signed), permission changes, IR/root/TTY enforcement,
duplicate audit rejection and actual exclusive grant writes preserving three
existing grant files. The top-level menu regression intercepts Python to prove
the shortcut calls only the existing helper and returns on HOLD/missing helper.
Existing signed-intent, durable nonce, root-broker, bridge, KH inventory migration
and pairing regressions remain unchanged.

Local validation on 2026-11-01: **122 Python tests passed**, plus the existing
Backhaul management shell suite with the new shortcut regression, `bash -n`,
and `git diff --check`. Python suites: root review (14), signed intent (9),
nonce ledger (10), root broker/provisioning (30), XHTTP bridge (8), KH inventory
migration (16), pairing regression (14), Smite inventory (7), Smite route intent
(5), and Smite route lifecycle (9). Smite lifecycle used an isolated virtualenv
with repository-pinned direct dependencies. No live-host or client traffic test.
