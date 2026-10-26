# Smite Stage 13 — Two-host release admission (READ ONLY, DRAFT)

This is **not a deployment wizard** and **cannot enable secure Node
control**. Stacked on U-OPTI Stage12 PR #34 and companion to the still
draft Smite Panel/Node protocol PRs. No work was performed on IR or KH.

## Why this gate exists

- Signed Node traffic is only safe if the Panel and Node images contain
  the intended HMAC/pairing modules and no stale host Overlay shadows them.
- Docker's unsigned legacy Agent healthcheck is incompatible with strict
  HMAC mode.
- A root-owned Node identity/replay directory and separate Panel
  encryption/origin approval are needed before both sides can switch.
- HMAC signs the **exact Agent HTTP target**. Nginx path rewriting,
  wrong SNI/TLS, a proxy or mismatched gateway path can break or weaken
  the intended control traffic.
- A saved *snapshot number* is not proof that the provider has an
  accessible, working snapshot, or that rollback procedures have been
  exercised on both machines.

## Stage13 read-only report

`modules/smite-stage13-preflight.py` emits clear lines with
`PASS_LOCAL_EVIDENCE`, `HOLD`, and `UNVERIFIED`.
Even if all locally testable checks pass, it ALWAYS prints:

```
AUTH_ACTIVATION=BLOCKED
STAGE13_DEPLOYMENT_AUTHORIZED=NO
```

It never runs Docker, `nginx -t`, `systemctl`, `curl`, external
network requests or writes a configuration. The standalone experimental
`u-opti --smite-pairing` menu gets additive option **9** to choose
the actual `ir`/`kh` role and inspect the host without changes.

Local checks:
1. Exactly matching saved Standard role (`panel-iran` for IR,
   `foreign` for KH). Private Network mode intentionally HOLD.
2. Root/service-owned `0600` paired identity inside `0700` directory,
   with valid UUID and HMAC key shape; no key material printed.
3. Existing loopback-only `127.0.0.1:8888` Node Compose and the
   0600 Stage9 **INERT** signed-auth Compose candidate, including
   separate read-only identity, writable replay directory and
   unsigned root liveness healthcheck.
4. Replay directory private 0700 and existing DB mode 0600 if present.
5. A private versioned `security-image-lock.json` holding distinct
   Panel/Node **digest-pinned** image references. This checks format,
   not registry integrity or the effective running image.
6. Stage10 source-parity audit against manually extracted/reviewed
   Panel and Node image `/app` trees plus current U-OPTI overlay
   sources/Compose mounts. Missing modules or stale overlays HOLD.
7. A private versioned `snapshot-receipt.json` containing both IR/KH
   snapshot references and `rollback_steps_reviewed=true`.
   This is evidence of a *recorded plan*, not a provider verification.
8. Source-only Nginx TLS/443 layout: KH `/api/agent/` path preserved
   to 127.0.0.1:8888 with allow/deny; IR `/api/node-control/`
   forwarded to local Panel 8000 without URI rewriting.
9. On IR, a private versioned administrator-approved Node origin map.
   It cannot be generated from unauthenticated registration metadata.

**Not verifiable offline:** GHCR signatures/provenance, effective
container digests/UID/mounts, actual resolved Nginx conf, certificate,
SNI and query-byte forwarding, IP allow-list provenance, provider
snapshot restore, live FRP/Backhaul/XHTTP client traffic, secure
rollout sequencing and post-reboot rollback.

Examples of *documentation-only* receipt structure — replace with
real operator-approved details after inspecting provider accounts:

```json
{
  "version": 1,
  "snapshots": {
    "ir": "real-ir-provider-snapshot-reference",
    "kh": "real-kh-provider-snapshot-reference"
  },
  "rollback_steps_reviewed": true
}
```

And the image lock:

```json
{
  "version": 1,
  "images": {
    "panel": "ghcr.io/your-org/smite-panel@sha256:<64-hex-digest>",
    "node": "ghcr.io/your-org/smite-node@sha256:<64-hex-digest>"
  }
}
```

These files are not created automatically; fabricate neither digest nor
snapshot ID. Store each privately as mode 0600 under 0700 host directory.
The sample image-lock placeholder is not an accepted digest, on purpose.

## Default paths and explicit overrides

Each file source can be provided via an explicit CLI option, e.g.
`--nginx-vhost`, `--panel-app`, `--node-app`,
`--panel-compose` and `--node-compose`. This matters because
the real KH Nginx domain-specific vhost can have a different filename
and current host installs can have no extracted image source trees.
Do not try to synthesize these sources from the network during preflight.

The tool can be run on isolated test fixtures and the GitHub CI does
exactly that for IR/KH role mismatch, missing or untrusted secrets,
replay permissions, nonexistent snapshot evidence, spoofed image pins,
stale mounted overlays and rewritten HMAC targets.

## Explicit IR old-key restore admission (2026-10-20)

Existing U-OPTI `modules/smite-stage13-preflight.py` now accepts an
**explicit operator-requested IR restore check** (NOT a new menu or
automatic installer activation) via `--recovery-old-node-id` and
`--recovery-witness-sha256`, with `--panel-database` and
`--panel-revocation-witness` paths. It verifies Smite's exact witness
JSON contract and externally trusted SHA against a private, quiescent,
real Panel SQLite snapshot opened read-only. The old Node must be
revoked with the same timestamp and have zero outstanding pairing
codes. Missing, corrupt, unsafe, uncheckpointed or rolled-back state
HOLDs. Missing one input, wrong role or untrusted SHA also HOLD.

Only use this option with a **separately approved offline IR restore**
after stopping both signing sides and independently retaining the
witness SHA outside the Panel backup. A normal fresh install does not
require an old-Node revocation witness and returns `NOT_REQUESTED`.
A PASS means local evidence matched; it **never** authorizes starting
signed traffic, Docker activation, restored identity adoption, or
production release. The CLI's nonzero exit contract is unchanged.

Both the KH replay marker check and this IR restore check are distinct:
a KH pass does not prove an IR witness; one host's offline state is
not a signed two-host restart or rollback proof.

## Remaining stage — coordinated operator-approved integration

1. Review the stacked Smite/U-OPTI Draft PRs into one tested release
   candidate. Port remaining U-OPTI FRP/Backhaul/Node metadata overlays.
2. Create and verify immutable Panel+Node image digests/attestations.
3. Confirm actual Node identity UID permissions, Panel Fernet master
   backup and database migrations, and trusted pinned destinations.
4. Confirm effective TLS/443 signed endpoints with non-production nodes;
   test invalid signature/nonce/replay, signed register/apply/remove
   and no unsigned fallback.
5. Verify cloud snapshots and perform a rollback rehearsal (provider
   external evidence), then a supervised two-host trial on disposable
   test VPS; test real FRP/Backhaul/XHTTP traffic before/after reboot.
6. Only after that decide version and promote a reviewed release.

**A local PASS is never a production security approval. No commands
need to be run on the user's IR or KH right now.**
