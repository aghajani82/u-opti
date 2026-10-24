# U-OPTI closeout — atomic INSTALL_REF and paired Smite artifact admission

**Reviewed 2026-10-20** · [One continuing Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) · [Closeout Issue #47](https://github.com/aghajani82/u-opti/issues/47)

## Issue fixed in actual install and update source

`INSTALL_REF` was a separate best-effort file written **AFTER** the
journaled program-file commit, so a crash could leave new `VERSION`,
`u-opti` and modules alongside an outdated or absent persisted update
channel. In the revised code the single transaction applies:

1. the reviewed staged executable, common library, version and modules;
2. **`INSTALL_REF` as the last hashed, journaled target** with 0644
   permissions, derived from the validated user-selected Branch/ref.

Both `install.sh` and interactive `u-opti` Update save the previous
`INSTALL_REF` under their persistent private backup directory (or a
`.INSTALL_REF-was-missing` marker), then invoke the existing
`u-opti-update-transaction.py apply ... --source-ref "$BRANCH" ...`.
Neither directly writes `INSTALL_REF.new` after the commit anymore.
Recovery preflights the old/new metadata hashes and restores the exact
previous channel, **or its absence**, together with the old modules
before restarting a restored old launcher.

**Backwards compatibility:** pre-existing version 1 pending journals
without an `INSTALL_REF` entry still restore using their recorded file
set; schema and bundled independent rescue behavior were not silently
upgraded or invalidated.

Negative/safety checks: invalid refs (path injection, spaces, newline)
HOLD before a live write; modules cannot disguise themselves as
`INSTALL_REF`; unrecognized paths in a recovery journal HOLD.
The long-standing Backhaul packaging CI explicitly asserts the new
four-file standard backup count **and** source-ref journaling, rather
than leaving an outdated three-file assumption.

**Tests:** real isolated Bash fresh/legacy installer block,
intentional installer SIGKILL after `INSTALL_REF` changes, old ref
restoration and ref-absent legacy restoration; independent real
transaction helper tests cover atomic final metadata commit, deliberate
`os._exit` after changing metadata, bad ref, and older no-ref journal
compatibility. All avoid production filesystem/network.

## Source pairing investigation — no unsupported release claims

- The **default Smite installer** in this U-OPTI branch still pins
  `SMITE_UPSTREAM_VERSION=0.1.7`, upstream `zZedix/Smite` and
  historical `ghcr.io/zzedix/smite-panel` +
  `ghcr.io/zzedix/smite-node` digests. The stable path is not the
  newest security candidate.
- The experimental `SMITE_INSTALL_PROFILE=clean-rc` invokes
  `smite-clean-image-pair.py` and
  `smite-stage15-bundle-verify.py`, which check both offline
  archives' hashes, image IDs and source commit, *given external
  trusted source and manifest checksums*. Those image IDs are **local
  Docker image IDs, not registry digests or signed release attestation**.
- The latest reviewed Smite strict replay lifecycle is
  [Smite Draft #16](https://github.com/aghajani82/Smite/pull/16)
  at `3751aeda6f946e5e5624e5e89ab1ce554fec4460`,
  with explicit first-time replay DB bootstrap. This SHA is used in
  relevant U-OPTI compatibility tests, **not** yet as a universally
  selected installable Panel+Node artifact pair. It does **not** prove
  a published immutable production registry image exists.
- **Release admission still HOLD:** choose one specific U-OPTI HEAD,
  Smite HEAD, Panel image digest and Node image digest, prove each
  artifact was built from the reviewed source and verify the paired
  offline manifest before turning on strict auth or changing default
  installation. Signed/authenticated provenance and an operator
  recovery path are still required.

## Non-goals and remaining risks

This is file **metadata integrity within an interrupted install**,
not an immutable signed provenance record. The resolved GitHub
`SOURCE_SHA` is used for coherent downloads but is not yet separately
persisted as a verified `INSTALL_SHA` record in the journal. A final
approved source/image digest manifest remains missing.

No actual IR↔KH routing tests, provider power loss, real first migration,
Smite replay bootstrap/key rotation or FRP-independent Backhaul activation
were performed here. Existing live hosts and `main` are unchanged.

**Next priority:** reconcile the immutable source/image digest pair
and safely integrate strict replay bootstrap, then independently
qualify Backhaul without FRP while preserving the simple IR→KH flow.
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.
