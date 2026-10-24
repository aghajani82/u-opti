# Smite signed Node: first replay enrollment + durable marker (offline review)

**2026-10-20 · Single closeout workstream**: [Issue #47](https://github.com/aghajani82/u-opti/issues/47) · [U-OPTI Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) · [Smite Draft PR #16](https://github.com/aghajani82/Smite/pull/16).

**Status: LAB VERIFIED · STRICT PRODUCTION ROLLOUT HOLD.**

## Why it was needed

Smite's `DurableNonceStore.initialize_new(database, node_id)` already
provisioned SQLite explicitly and refused request-time recreation. But an
operator mistakenly running a first-time bootstrap again **after the
database was lost** could still make a new blank store. A new store cannot
remember previously consumed, still-valid HMAC nonces.

The reviewed Smite Node source now contains
`node/app/replay_enrollment.py`, an **offline one-time** enrollment
primitive. It intentionally:

1. Requires an existing paired Node identity (private, same process UID,
   0600 JSON), not a new identity or pairing secret.
2. Requires the identity and replay SQLite parents to be **separate,
   already-mounted persistent** owned private 0700 directories, neither
   symlinked, with absolute paths.
3. Requires the exact opt-in `--confirm-first-provision` flag. Before
   constructing the DB, durably writes a private 0600
   `replay-enrollment.json` marker **beside the Node identity**, recording
   only schema, Node ID and replay DB absolute path, never the HMAC key.
4. Provisions SQLite once using `DurableNonceStore.initialize_new`,
   checks that the identity has not changed and the DB matches that Node.
5. Refuses *any* attempt when the marker **or** database already exists,
   even if one is corrupt. Errors retain data and mark HOLD. Never delete,
   rotate, reinitialize or auto-retry.

**Independent persistence matters**: if the replay DB volume disappears
but the identity/marker volume survives, bootstrap is blocked instead of
mistaking the loss for first boot. The signed Agent API already returns
503 on unavailable replay storage. If **both** volumes are lost,
the local marker alone cannot prove historical enrollment. It also
cannot detect an older **same-identity** snapshot with missing nonce
history. Correct recovery still requires an independently approved
quarantine/time-window policy (with verified time), or coordinated
authenticated key rotation, before any signed traffic resumes.

## U-OPTI integration / current limitations

- U-OPTI paired-identity preparation currently stores the private
  preview credentials under `/etc/u-opti/smite/identities`. The Node's
  strict runtime default expects
  `/etc/smite-node/identity/node-identity.json`, with the separate
  replay SQLite path `/var/lib/smite-node/auth/agent-replay.sqlite3`.
  **These are NOT automatically reconciled or mounted by this patch.**
- Neither U-OPTI's existing Smite installer nor its enrollment wizard
  automatically invokes the new tool. It deliberately cannot be reached
  through an inbound HTTP request or container startup.
- The user-facing clean process remains IR Core → KH Core → KH Sanaei
  inbound → dynamic port/path → selected FRP or Backhaul tunnel.
  One-time signed provisioning should eventually be a guarded internal
  part of approved KH Node pairing, not an additional required wizard maze.
- Any future approved installer must enforce *both* persistent bind
  mounts and preserved permissions before switching
  `SMITE_AGENT_AUTH_MODE` from its default `legacy` to `strict`.
  Missing mount/identity/marker, stale restore or uncertain provenance
  must HOLD, not create another empty DB.

## Evidence, source pins, test scope

- Smite source code used in cross-repo tests and the CI image bundle:
  `9201722336b05e833408a0a352cfee99465da2cb`, on existing
  Smite [Draft #16](https://github.com/aghajani82/Smite/pull/16).
- [Smite Signed Agent CI run 39395144111](https://github.com/aghajani82/Smite/actions/runs/39395144111) passed explicit
  first boot, duplicate/replay loss HOLD, partial provisioning marker
  persistence, permissions/symlink refusal, CLI confirmation and
  no-secret-logging regression.
- [Smite Stage15 paired offline image run 39395144038](https://github.com/aghajani82/Smite/actions/runs/39395144038)
  succeeded on the same source SHA, without image publishing.
  Temporary artifact ID `12251038624`, ZIP digest
  `sha256:2cef44711afed60666a6ec347a8e0b156d11a40609db913d6183ea879771e557`,
  separate manifest SHA256
  `f40c6553a1573c6623f03634da187fe0a403a309590871045a8c0bcada6b590f`.
  **Expires 2026-10-23T08:42:39Z.** IDs and archive ZIP hashes
  are not registry-distributable image digests.
- Existing U-OPTI [Draft #48](https://github.com/aghajani82/u-opti/pull/48)
  updated pinned strict FastAPI and real Nginx/443 integration CI to
  Smite `9201722...`. The disposable FastAPI test now uses the actual
  one-time enrollment tool, verifies the independent ledger, then
  simulates DB loss and refuses re-enrollment even across ASGI restart.
  [U-OPTI CI run 39395426015](https://github.com/aghajani82/u-opti/actions/runs/39395426015)
  completed successfully with 16/16 jobs passed.
- The Smite PR may later advance to documentation-only commits.
  Only the exact code SHA above was used for the tests/image
  evidence; never silently substitute a newer HEAD and cite older CI.

**Next important blocker:** design and test production-grade KH private
bind-mount and pairing-first enrollment transactions, including
operator-independent marker preservation, idempotent restart,
quarantine/key rotation after restore, and a safe UX. Until then no
`main` merge, image release, live server mutation or automatic
strict-mode enablement. `INSTALL_ALLOWED=NO` · `ACTIVATION_GATE=HOLD`.
