# Stage15 active-owner continuation — 2026-10-30

Update: an executable Panel-only migration candidate and recovery tests now
exist. See [the migration runbook](SMITE-STAGE15-PANEL-MIGRATION.md). The
missing-implementation notes below record the earlier review; live validation
remains pending.

Status: **HOLD — no approved active-runtime migration**. This is a source/test
candidate, not an installation authorization. No IR/KH commands were executed.
Grandoptical is outside scope. Do not run the old `smite-stage15-upgrade.py` on
an enrolled WSS runtime with an active owner. No PR merge or stable release.

## Reverified source and image evidence

Starting heads remain U-OPTI `acfa81b84a45b4efc34c2d1998e20f2ee5c375d8`
and Smite `8edbd4032ae657fe2bb38cd9b3290de5f1e07a54`.
The existing image build is successful, so rebuilding identical source is not
required to manufacture a new result:

- Build: https://github.com/aghajani82/Smite/actions/runs/40921424209
- Artifact ID: `12919495217`, created 2026-10-29, expiration 2026-11-01.
- ZIP SHA256: `d250b0fd27ae362bc4008b9e62208f94ae92fb71273d66bee83c9bcdcd1f75d9`.
- Manifest SHA256: `67672e362686b886a6e5653055ad808d1d878c514ee2e6c2f75f310eb77ef4cb`.
- Source: `aghajani82/Smite@8edbd4032ae657fe2bb38cd9b3290de5f1e07a54`.

| Role | Build image / OCI index ID | Docker config SHA256 | Archive SHA256 |
| --- | --- | --- | --- |
| Panel | `sha256:4abfd55d5c18d95119f8bae4c790cb2b687c54355836ea5529c8aff8a53dcd09` | `9e88d664bd42e5c1ccb09bfe36d22cce9c0ee84d3a0e44146ffacd2542307f06` | `7b3d3172788d62f7d60f7103965e04db0df01606c4bc8d03760f904006ecf7c3` |
| Node | `sha256:1805f8477341c3c97d77d5ab895250ee1ffac6a14a45f5a2ca83720314324150` | `96789708e2bd8be0550b5aa4d496b12a269ae8d9bccceecad551c757798875c4` | `f4b4f1696582ba408ba85d581fa0dddd6ba04cd5d632e46eec95755f8d78e730` |

The archives were downloaded and checked locally without Docker execution.
Both Docker manifests, OCI index-to-config links, blob digests, compressed layer
contents/diff IDs, amd64/Linux platform and source revision labels passed.
Containerd index IDs differ from Docker config IDs: do not substitute one for
another in existing admission pins. These checks establish content consistency
against a separately trusted manifest, **not** a signed publisher attestation.
Actual target-engine load/inspect and new-runtime compatibility remain NOT_TESTED.

Download using the Actions run above while the artifact exists; verify ZIP hash
before extraction into an isolated empty workstation folder. Only the two named
archives and `stage15-images.json` are expected. Then, from this checkout:

```sh
python3 -B modules/smite-stage15-bundle-verify.py \
  --folder /absolute/path/to/extracted-bundle \
  --source-sha 8edbd4032ae657fe2bb38cd9b3290de5f1e07a54 \
  --manifest-sha256 67672e362686b886a6e5653055ad808d1d878c514ee2e6c2f75f310eb77ef4cb \
  --inspect-archives
```

Exit 2 remains intentional even after successful content verification:
`STAGE15_DEPLOYMENT_AUTHORIZED=NO`. Expired artifacts must not be replaced with
an unverified mirror or an image from a different commit.

## Confirmed migration gaps; do not bypass them

1. `smite-stage15-wss.py:health` checks both the reviewed image set and the full
   runtime signature recorded in the WSS journal. Merely loading/tagging a new
   Panel fails that contract. Editing the old journal or broadening the allowed
   image set is not a safe migration.
2. A paired image upgrade recreates Node containers. The active FRP processes
   belong to those Nodes. This is incompatible with the current owner-preservation
   constraint. A Panel-only upgrade cannot silently claim the KH Node implements
   newly added custom-path inventory validation.
3. Root Broker worker/planner hashes are pinned. They must be migrated together
   with their configuration using verified root-owned before-images. Copying
   new module files alone is insufficient.
4. No tested transaction currently combines all three transitions with rollback,
   recovery, and the existing live Signed/Replay/WSS state. An exploratory
   mutating migration was therefore not shipped or wired into installation.

## Required transaction before live approval

Implement and test an explicit versioned receipt separate from both WSS journals.
Bind it to the original journal hashes, actual old/new image identities, full
runtime security signatures, owner ID/spec, Node container/PID, FRPS PID/start
and socket set, worker/planner/config before/after hashes, and immutable Nginx
configuration. Do not record or print secrets in reports.

Before mutation: verify independent signed owner and KH inventory proofs; check
existing Panel key and Node socket mounts, UID/GID permissions, singleton owner,
no duplicate leases, no pending route transaction, no automatic startup reapply,
SQLite integrity, available disk, and root ownership/modes. Back up Panel SQLite
through its backup API and save old image content, verify digests, fsync backups
and PREPARED receipt. Retain identity/replay files and open replay DB unchanged.

During mutation: serialize against engine and broker operations; stop admission
before changing a pinned file; never recreate a Node. Permit only explicit
before/after values. Check the owner process and protected state at every phase.
On failure, keep admission closed and retain phase/before-images. Recovery must
validate drift before any write. Never restore old Replay or Panel DB over a
live runtime. A candidate needing Node replacement requires a separately reviewed
maintenance design and must not be slipped into a Panel-only procedure.

## Conditional IR/KH test sequence — not executable rollout instructions

All live stages below require separate user approval and are currently NOT_TESTED.
Do not begin Apply while the migration gaps above remain open.

1. **Snapshot — IR and KH:** with console access, capture VM/disk snapshots and
   separate verified backups of configs, identities, journals and DBs. Record
   existing owner/container/process identities. Snapshots are evidence/recovery
   material, not permission to revert a live Replay database.
2. **Preflight — IR:** validate current broker pins, root ownership, WSS/edge
   journals, Nginx TLS/SNI/KH allowlist, exactly one FRPS and existing owner port.
   **KH:** validate signed inbound inventory with the actual selected port/path,
   WSS and unchanged Node/FRPC identity. Neither example port nor path is a default
   authorization. Obtain runtime/engine facts before selecting an image identity.
3. **Apply — IR:** BLOCKED pending validated active-runtime migration; do not
   install a new image, restart services, edit Nginx, reapply or delete the owner.
   **KH:** no image replacement authorized. Following future successful migration,
   bridge publication and exact independent Root TrustedGrant are separate steps.
4. **Verify — both:** recheck Signed/Replay rejection, WSS/edge, TLS443, owner PID,
   no extra FRPS/child, signed inventory, route collision protection and exact
   grant. Test actual VLESS/XHTTP client traffic; UI Active is insufficient.
5. **Rollback — IR:** requires separate approval and a validated transaction.
   Remove any route/grant/bridge in dependency order before reverting its runtime;
   verify hashes and owner continuity. **KH:** no changes means no rollback action.
   Unknown drift, missing backup, changed process, invalid signature, stale proof,
   journal mismatch, duplicate port or failed Nginx validation means STOP.

## Test scope

New archive tests cover classic/config and containerd/index identity, content
corruption, source mismatch, wrong role tag, graph/layer mismatch, duplicate
members, traversal, links, descriptor size, ambiguous images and symlink input.
Independent root-review tests cover exact digest confirmation, audit-before-grant,
cancellation, expiration during review, noninteractive callers and request swap.
Existing cross-repository security tests remain enabled; none were removed.

Live installation, active-runtime upgrade/rollback/recovery, target Docker load,
and real end-to-end client traffic: **NOT_TESTED**. Artifact availability is
short-lived; durable authenticated delivery remains a release prerequisite.
