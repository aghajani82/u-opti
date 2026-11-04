# Issue #102 — Signed Backhaul host review (no live install)

Status: **READ ONLY / INSTALL_ALLOWED=NO / ACTIVATION_GATE=HOLD**

This is the current first gate for **Backhaul beside existing FRP**, not a
production installer or authorization to restart/recreate the RC7 Node.

## What changed

The existing `Independent Engines → Backhaul → 2 Review installation prerequisites`
may now receive independently sourced, cryptographically verified **paired
Smite registry image** evidence. No existing menu choices, Docker processes,
network routes, tunnels, Xray clients, or installed files are modified by this
review.

It reuses the existing
`modules/smite-registry-pair-admission.py:verify_pair()` verifier, which
enforces exact externally reviewed manifest SHA-256, immutable Smite source SHA,
exact signed release tag, Cosign OIDC publisher workflow identity,
signed node/panel roles and image digests. It does not automatically trust
`docker inspect`, image labels, GHCR tags, a local file alone, or the old
RC2 candidate. Cosign verification can read GHCR/Sigstore but **never**
installs or pulls the image.

## How the existing review accepts provenance

When a **genuinely independently reviewed signed pair** is available and the
operator has separate proof of the *exact* file hash/source/tag, the existing
read-only option accepts the following *optional environment variables*:

| Variable | Value / boundary |
|---|---|
| `SMITE_BH_PAIR_MANIFEST` | Local non-symlink JSON candidate, supplied by approved release review |
| `SMITE_BH_PAIR_SHA256` | Independently reviewed SHA256 of those exact bytes, not computed as proof from the same untrusted file |
| `SMITE_BH_PAIR_SOURCE_SHA` | Independently reviewed 40-character Smite source commit |
| `SMITE_BH_PAIR_PUBLISH_REF` | Exact signed `refs/tags/v...` release identity |
| `SMITE_BH_PAIR_TRUSTED_ROOT` | Optional trust-root file; existing verifier checks its reviewed SHA pin |

Provide all four required fields **in the environment of the U-OPTI process**,
then open the normal Backhaul review option 2. Alternatively, the existing
`smite-managed-engine-host-admission.py` read-only CLI accepts matching
`--signed-pair-*` arguments. No changes to server config files or launch
scripts are required.

**Do not invent these values, copy a digest from live Docker, reuse the old
RC2 sample as an RC7 proof, substitute a local image ID, or set the proof
flags based on a green CI run.** If current runtime has no suitable signed pair
release evidence, the correct result remains
`REASON=EXPECTED_NODE_DIGEST_REQUIRED` and `INSTALL_ALLOWED=NO`.

On valid Cosign proof **and** matching runtime image reference, the report
can set `SIGNED_REGISTRY_PAIR_PROOF=COSIGN_VERIFIED`; this proves only the
pair of registry references, **not** that running container bytes,
persistent replay ledger, FRP owner/child state, or prior tunnels have been
attested. Consequently `NODE_RUNTIME_BYTES_AND_REPLAY=UNVERIFIED`,
`HOST_TRANSACTION_AND_ROLLBACK=NOT_IMPLEMENTED`,
`INSTALL_ALLOWED=NO`, and `ACTIVATION_GATE=HOLD` remain unchanged.

A mismatch or incomplete proof returns a redacted fail-closed reason:
`INCOMPLETE_SIGNED_PAIR_PROOF`, `SIGNED_PAIR_PROOF_INVALID`,
`SIGNED_PAIR_IMAGE_PIN_CONFLICT`, or `NODE_IMAGE_DIGEST_MISMATCH`.
No secrets, UUIDs, tokens, full Compose files or signatures are emitted.

## Production blockers still OPEN — do not bypass

- Actual IR/Grandoptical running Node digest and complete signed RC7 runtime
  inventory must be checked independently; two-host operator approval required.
- `SAVED_TUNNELS=EXISTING_DO_NOT_RESTART` is a **hard HOLD**. Three current
  FRP tunnels (`20182`, `optical`, `nahavi`) must remain unchanged.
  `SAVED_TUNNELS=UNKNOWN` means no observation, **not zero tunnels**.
- Existing `smite-managed-backhaul-host-executor.py` is **disposable-host
  test only** and requires `SAVED_TUNNELS=ZERO`; it may force-recreate
  `smite-node`. Do not call it, relax the guard, or adapt Sidecar test-host
  markers for the live servers.
- An explicitly proved real-host transaction still needs independent backup
  and recovery-console proof for **both** hosts, byte-exact FRP owner/child,
  signed Node health + replay, Broker socket, 443/TLS and rollback
  before/after, plus isolated real shared-WSS regression.
- No Backhaul public port/XHTTP inbound or Nginx route should be created
  until all these gates pass and the operator approves the deployment.

The PR changes only this read-only signed-provenance bridge and negative/positive
CI tests. **It is not acceptance of Issue #102 as complete.**
