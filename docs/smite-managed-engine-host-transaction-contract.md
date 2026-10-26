# Independent Smite Engines — real-host transaction contract (READ ONLY)

2026-10-19 · U-OPTI draft PR #38. **This is NOT a production installer.**

The last stage implemented one shared read-only IR/KH admission for Backhaul
and FRP. This stage adds `smite-managed-engine-host-plan.py`: an explicit
**reproducible, non-authorizing host transaction proposal** that requires
a reviewed managed/strict Core, a private official engine candidate tied
to the exact current Compose, absent target engine, no saved tunnels and
no unverified second-engine enrollment. It cannot run Docker, download
packages, configure 443, issue HMAC tokens or mutate the filesystem.

## Planned safe execution sequence (future executor only)

1. Acquire a **shared exclusive transaction lock** for Backhaul and FRP;
   reject unresolved journals and any changed Core/profile/tunnel data.
2. Independently confirm a restorable cloud Snapshot and emergency console
   for **both** disposable hosts. No self-attested JSON is accepted.
3. Verify official archived binary provenance, exact architecture, both
   `frpc` + `frps` (for FRP), other engines unchanged, and no drift from
   the previously reviewed Compose SHA-256.
4. **Persist and fsync a private crash-recovery journal BEFORE any file
   mutation**, storing exact prior Compose/manifest bytes, protected
   persistent identity/replay/tunnel digests and expected rollback modes.
5. Stage only the target engine's files and read-only mounts. Never
   install the other engine or request forwarded ports/paths during setup.
6. Recreate only the reviewed Smite Node. Recover if the host loses power.
   Do not touch Panel, 3x-UI, Nginx, firewall or unrelated containers.
7. Require signed Node API `ready`, replay defense, private health and
   persistent identity after restart; refuse unsigned local-only claims.
8. On failure, restore exact journaled state, restart only the original
   Node, confirm signed prior inventory and keep evidence on any drift.
9. **Only after separately reviewed host admission + operator approval**
   may a future executor commit and update user-facing status.

These are **contract requirements**, not performed actions.
`PLAN_SHA256_NOT_AUTHORIZATION` is only a deterministic change detector,
not a signature, ticket, install secret or approval. Even a passing
staged FRP plan reports `INSTALL_ALLOWED=NO` and `ACTIVATION_GATE=HOLD`.
Commands `install` and `rollback` exit 2 without changing a machine.

## Backhaul provenance hardening completed in this draft

The earlier v0.7.2 Backhaul stage stored only a hash claim and editable
SHA256SUMS, so a modified ELF and recomputed hashes could spoof it. This
was **not acceptable** for real-host activation.

The experimental Backhaul package now retains the official tarball
(`backhaul.official.tar.gz`) in private staging. Verification checks
both the release-pinned archive SHA-256 and exact executable bytes
re-extracted from that archive. Rewriting local staging checksums,
manifest or summary without changing the pinned archive cannot authorize
a forged executable. An old archive-less stage fails closed.

The host plan now recognizes **both** archive-bound Backhaul and FRP
candidate types, but *never* authorizes real installation: snapshot,
console, signed Node health, host crash-recovery executor and approved
two-host 443 acceptance are still unresolved. Reproducible synthetic
archives in unit tests are fixture-only, not deployment authority.

## CI coverage and one-rebuild policy

`tests/test-smite-managed-engine-host-plan.py` covers **both** archive-bound
engines with synthetic test-only pinned archives, deterministic plan
hash, unchanged host files, cross-engine manifest drift, Compose
drift, unsafe stages, saved tunnels, incomplete Core, missing snapshot
approval and disabled install actions. Additional Backhaul tests
rewrite **all** local staging hashes and confirm archive re-extraction
still rejects forged bytes. Existing CI still covers Docker
Compose force-recreate and signed inventory/rollback on isolated hosts.

No `main` changes or test-VPS writes. Do **not** Rebuild the current
U-OPTI 0.16.7 / working Smite FRP + Backhaul servers until the reviewed
host executor, official provenance, signed 443 transport, snapshot
recovery and BOTH-host acceptance have been approved and tested.
