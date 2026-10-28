# Stage15 Signed Pairing bootstrap correction (disposable IR only)

This fixes source-level replay preparation, not a production release. Signed
runtime activation on the operator's IR remains untested by this PR. No server
was accessed or changed. The reported IR hotfix reached `STAGE9=PREPARED` only.

## Reviewed inputs and trust boundary

The supplied candidate patch applies to U-OPTI main
`ee3ff1e689c71a80479b0192dc099b69a1956578`. Its reconstructed-source tests were
replaced with imports of real repository modules and isolated filesystem tests.

The local Node ID is independently anchored in the successful
[Smite Stage15 run 40461876836](https://github.com/aghajani82/Smite/actions/runs/40461876836),
[job 122048191494](https://github.com/aghajani82/Smite/actions/runs/40461876836/job/122048191494),
source `4e16633a304db6c03f7f2911cc7d77213b0c4ec1`. Its build log records Node
`sha256:a417e8c28426da5eaf16d59925d5c89b52dbf7849ca560dfa9a765a1266b3991`
and manifest SHA256
`fe32c9c54714cfdb482f27112829eba13d5188e9e1e7e26c7266d8d54e85462a`.
The workflow's source/revision checks, image first-boot and signed/paused rollback
gates succeeded. This is reviewed test-image provenance, **not** a signed registry
release or proof that live IR activation has passed.

The exact local tag is admitted only if BOTH its current image ID and the running
Node image ID equal that independently reviewed constant. Enrollment runs by the
immutable ID, with `--pull never`, network disabled, all capabilities dropped and
no-new-privileges. Unknown tags, changed IDs, failed inspections, malformed output
and invalid replay artifacts HOLD. No pin is learned from runtime metadata or
from an untrusted local manifest. Existing immutable GHCR admission is retained.

The existing shared `/var/lib/u-opti` may remain root-owned 0755 (no group/other
write); dedicated `smite-node-security` and `replay` remain exactly 0700. Symlinks,
wrong ownership and unsafe modes are refused, never repaired by chmod. New
shared parents retain the existing conservative 0700 creation behavior.

Subprocess failures report fixed operation labels. Only exact allowlisted helper
errors become specific reason codes; unknown stderr, stdout, command arguments,
credentials and exception strings are never copied into the displayed failure.
HMAC, credential redemption, replay continuity and explicit activation gates are
unchanged. Preparation does not start Node or Tunnel.

## Validation

`tests/test-smite-stage15-pairing-regression.py` exercises real modules, with only
Docker transport mocked. It tests storage modes/ownership/symlinks, image identity,
no automatic runtime activation, replay fail-closed behavior and safe diagnostics.
The existing Stage9 preparation test also verifies unchanged base Compose,
identity and state under a shared 0755 directory. Existing pairing tests cover
activation opt-in, replay key binding and signed rollback.

Main CI runs the new regression. All five dedicated registry/XHTTP security
workflows also trigger when these pairing modules change; their checks remain
unchanged. Merge requires successful checks on the final PR revision.

## After merge: operator procedure for the existing IR (do not run on KH/production)

1. Keep IR paused/strict. Preserve the existing secure backup/snapshot and the
   installed U-OPTI source before updating; backups containing identity material
   must stay root-only. Do not print `.env`, pairing codes or identity JSON.
2. Record the final merged commit SHA from the PR. Launch the existing updater
   pinned to that SHA, replacing the placeholder below. Select **Update U-OPTI**
   only; do not select install, resume, rebuild or any activation action.

   ```bash
   # IR ONLY — replace with the final reviewed merged commit SHA
   U_OPTI_BRANCH=<MERGED_COMMIT_SHA> u-opti
   ```

   The updater downloads a coherent source revision and does not itself apply
   the Node security candidate. Its selected ref is persisted; a pinned SHA
   will keep subsequent updates on that revision until explicitly changed.
3. Run the read-only candidate preflight:

   ```bash
   # IR ONLY — no runtime activation
   python3 -B /usr/local/lib/u-opti/modules/smite-node-auth-candidate.py --preflight
   ```

   Expected: `STAGE9=LOCAL_PREFLIGHT_PASS`, with activation still blocked.
   Preflight alone does not prove image admission or working signed traffic.
4. In a separate explicitly approved IR field test, open `u-opti --smite-pairing`
   and use the existing signed IR activation action with the already staged
   identity. Do not redeem again, delete replay state, or use legacy enrollment.
   Require all four success markers: `IR_SIGNED_NODE_RUNTIME=ACTIVE_FIELD_TRIAL`,
   `IR_SIGNED_NODE_CHECKIN=PASS`, `IR_LOCAL_HMAC_REPLAY=PASS`, and
   `PANEL_TO_IR_SIGNED_HMAC=PASS`. Verify no tunnel was started.
5. On any HOLD, retain the bounded reason code and stop. If runtime was touched,
   verify the existing rollback returned Node to paused/strict; do not assume a
   rollback attempt succeeded. Preserve identity and replay state. Do not rebuild
   IR/KH until signed IR acceptance is independently confirmed.

Grandoptical is out of scope. This PR neither publishes images nor changes the
Stage15 preview classification, and does not authorize a production rollout.
