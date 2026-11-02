# Smite RC7 installation provenance

Version: `2.0.0-rc.7`  
Source: `9a1270b31e8d44f13d09b71ab6b9798410b09c12`  
Release: https://github.com/aghajani82/Smite/releases/tag/v2.0.0-rc.7

Publisher: https://github.com/aghajani82/Smite/actions/runs/41424453332 — SUCCESS  
Independent verification: https://github.com/aghajani82/Smite/actions/runs/41424843913 — SUCCESS  
Manifest SHA-256: `58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e`

The exact manifest bytes are permanently stored in `modules/smite-selected-candidate.json` and the full pair is recorded below. The original publisher artifact is 13132245132; its temporary retention is not the sole evidence store.

```json
{"activation_allowed":false,"images":{"node":"ghcr.io/aghajani82/smite-node@sha256:03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263","panel":"ghcr.io/aghajani82/smite-panel@sha256:180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8"},"kind":"smite_signed_registry_pair_candidate","publish_ref":"refs/tags/v2.0.0-rc.7","release_approved":false,"schema":1,"source_commit":"9a1270b31e8d44f13d09b71ab6b9798410b09c12","source_repo":"aghajani82/Smite","version":"2.0.0-rc.7"}
```

The independent workflow checks both GHCR digests using Cosign 3.0.6, GitHub OIDC issuer, exact publisher workflow/tag identity, source SHA and image role. Installer admission retains those checks; unavailable registry/signature verification must HOLD without fallback. Manifest flags remain non-activating as required by the signed-candidate format; installation is an explicit menu action.

Official path: `Docker Management → Smite Management → Install Components → 1`.
Templates, CLI and images use the same application source. Image labels and `/api/status/version` are checked in CI. The real Panel image is checked for the built charcoal/teal frontend. Initial boot checks require zero nodes/tunnels and preserve unpaired Node fail-closed behavior.

Frontend TypeScript/build, theme/sidebar/MFA contracts, missing/malformed metric handling and initial Iran-only setup progress passed locally and in Smite PR #44. All eight PR jobs passed before merge. New U-OPTI qualification uses Ubuntu 24.04, anonymous signed image pull, isolated first boot, identity/replay rollback, real Docker volume retention and installer fixtures. CI run results must be checked on the final U-OPTI commit; this document does not predeclare pending runs successful.

Real public DNS/TLS, Iranian-network GHCR reachability, browser Login/Dashboard on the real VPS and reboot persistence: `PENDING_REAL_VPS`. No real VPS was available. No browser screenshot of the built frontend was captured in this execution. CI and static responsive/language contracts are not real-server validation.

No live server changes, Foreign Node installation, tunnel creation or Grandoptical operations. RC6 tag/release preserved. Console G/1 approval retained; no Passkey or independent Web Approval added.

## Iran VPS Sigstore TUF CDN 403 mitigation (2026-11-02)

The first real Iran host (Ubuntu 24.04, amd64) reproduced HTTP 403 for
`https://tuf-repo-cdn.sigstore.dev/14.root.json`. Cosign 3.0.6 correctly
refused to verify the signed RC7 bundle without trusted material. Both real
RC7 images passed independently in the operator's read-only diagnostic with
`--trusted-root` pointing to `sigstore/root-signing` commit
`c9aa2600c1492365922f1b3f351a208aa17d0e64` target `trusted_root.json` and SHA-256
`6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66`. No host installation was performed in that diagnostic.

v0.17.5 makes this **explicit reviewed trust snapshot** the only selected
RC7 fresh-install root, with checksum enforcement in the installer AND the
Python signature admission verifier. It does not download mutable TUF targets,
accept arbitrary certificate authorities or report live TUF metadata as
verified. A new Sigstore root rotation requires a separate audited U-OPTI
release. All existing digest, workflow identity, OIDC, role/source annotations,
transparency and unsigned-image rejection checks remain enabled. This is a
network compatibility repair, not approval of a production Smite release.

The menu pauses on failing installs to display the exact HOLD. Host Nginx,
real DNS/TLS, and successful live first boot still require operator trial.

## Fresh Iran host broker/journal directory mismatch (2026-11-02)

After the v0.17.5 signed-image checks and Nginx prerequisite passed on an
operator-owned new IR host, actual Panel provisioning reported
`HOLD_BROKER_DIRECTORY_MODE_MISMATCH`. Read-only inventory found root-owned
`/var/lib/u-opti` mode `0700`, `/var/lib/u-opti/rc6-install-journal`
mode `0700`, and journal `INSTALLING` for `panel-iran`. The journal's secure
`mkdir(parents=True, mode=0700)` is the source of the parent mode, while
broker provisioning had historically required `0755` for the same parent.

v0.17.6 accepts only existing modes `0700` or `0755` for that one root-owned
parent. It never changes an existing mode or relaxes requirements for private
journal/broker/grant children. Automated tests exercise an actual inert broker
provision against a journal-like `0700` parent and reject modes `0750`,
`0770`, `0777` and inappropriate `0700` at unrelated directories.

**Operator action:** retain interrupted journal and use official menu recovery
(Install Components → 7, guarded rollback) before fresh install. Do not delete
or chmod source/state paths. The IR host reports Ubuntu **26.04.1 LTS**; RC7
qualification remains Ubuntu **24.04 LTS** and no unsupported-host success is
claimed.
