# Stage15 — Verify delivered Panel+Node preview images without installing

**DRAFT / READ-ONLY / DOES NOT ACTIVATE.**

This phase bridges the gap between "the Smite GitHub source builds"
and "we have two identifiable image files that can later be tested."
Companion Smite Stage15 CI creates two offline Docker archives and a
manifest from the same exact source commit. GitHub Actions retains the
bundle for **3 days**; it is not a release, a signed OCI image or a
registry deployment artifact.

U-OPTI adds `modules/smite-stage15-bundle-verify.py`. The standalone
experimental `u-opti --smite-pairing` preview menu adds option **10**
to check a previously downloaded/unpacked workflow artifact.

The verifier requires:
- An absolute path to the unpacked bundle containing
  `stage15-images.json`, `smite-panel-stage15.docker.tar.gz` and
  `smite-node-stage15.docker.tar.gz`
- **Exact Git Commit SHA** from the trusted Smite GitHub Actions run
- **SHA256 of stage15-images.json** printed by that same run

It compares the trusted manifest SHA, checks the exact source commit,
both archive SHA256 values and sizes, distinctive local Docker image
IDs, the agreed `2.0.0-rc.0` proposal and that the manifest explicitly
says `activation_allowed=false`. It fails on a missing/tampered
archive, unexpected file name, additional role or wrong Commit.

It does NOT decompress or run image archives; it makes no network
request, writes no file, starts no container, and never touches Nginx,
FRP, Backhaul, secrets, Compose, SSH or currently running services.
**The command always exits nonzero**, even if the bundle files match,
so an installer cannot mistake checksum verification for permission
to deploy.

## From now to first safe use

The remaining milestones are NOT artificial numbered stages:

1. **Reviewed image publication and U-OPTI opt-in installer**:
   Verify trusted immutable image manifests and provenance, remove
   legacy host-Overlay conflicts and ensure correct paired Panel/Node
   source. Do not reuse U-OPTI's existing Smite v0.1.7 default images
   for signed security features.
2. **Two disposable VPS acceptance**:
   Restore/verify provider snapshots, install IR first and KH second,
   then install 3x-UI. Afterward configure dynamic inbound port/path
   and create the FRP/Backhaul tunnel in the management wizard. Validate
   Pairing, real TLS/443 HMAC both directions, Apply/Remove,
   FRP/Backhaul/XHTTP client traffic and reboot persistence.
3. **Release promotion**:
   Validate rollback, secret revocation, resilience to invalid HMAC,
   no anonymous fallback, compatibility checks and server snapshots.
   Only after passing these gates merge/tag/enable the release.

No guaranteed calendar delivery date follows from a successful CI
test. A failing acceptance condition must be fixed before promotion.

The main stable U-OPTI installer is unchanged; no GHCR push, release,
tag, Docker load, server activation or live host access was performed
by this Stage15 change.
