# Stage15 Secure Web Approval — pinned image distribution (source-only)

**Status:** cache-only implementation on U-OPTI draft PR #74. Not an installer,
not a migration authorization, not a production release. No IR/KH/Grandoptical
host modifications were performed by this source change.

## Why the original image downloader cannot be reused

`smite-stage15-fetch-images.sh` is pinned to the older Smite source
`6981bd91b43811fad8847da9abd81ef99a921003`. It is correct for
that reviewed FRP 0.71.0 pair and **must not be repointed or used as an
upgrade mechanism for a live Stage15 runtime with existing FRPS/FRPC routes**.
Its paired image upgrade preflight explicitly rejects active tunnels.

The Secure Web Approval preview images come from
`aghajani82/Smite@1f28222d80c29a9423da445c7e977cbc1867aead`,
Smite draft PR #41, Actions run `41079930810`, artifact `12988359565`.
The GitHub artifact expires **2026-11-02T15:23:45Z**. GitHub reports the
artifact ZIP SHA256 as:
`d7a5ab438b45bd05a46b42e97c9d925c3379adc6a06057e542b38091829bf63a`.
The successful isolated build job also emitted the exact `stage15-images.json`
SHA256:
`8c1e86220090ad960344d938c1d1d4c30ab656b07c54aff22a16e5d61482b4eb`.

## Separate, reviewed preservation gate — STILL PENDING

A maintainer must preserve **the exact existing artifact ZIP bytes** in a
public, disposable **prerelease**, named
`stage15-web-approval-images-1f28222d` (not the production release),
with asset **exactly**
`smite-stage15-offline-images-1f28222d.zip`.

Before publication, verify the artifact's Actions run ID, commit SHA,
successful security jobs, GitHub artifact `digest`, downloaded ZIP SHA256,
unmodified three ZIP members, exact manifest SHA256, and both inner archive
SHA256 and expected image identities. The ZIP may be renamed; it must **not**
be unpacked and re-zipped, rebuilt or silently replaced. The public Release
asset must be re-downloaded and hash-checked against the pinned ZIP digest.
Do not use a GitHub API token on IR/KH, do not upload an artifact ZIP to
either server, and do not promote via a mutable branch or tag.

**The prerelease is NOT confirmed published yet.** The fetcher intentionally
HOLDs on HTTP 404 or any mismatch; it never falls back to an Actions
download, different image, branch, latest, GHCR tag, or unpinned URL.

## Download-only operator entry point — AFTER prerelease publication

After a separate source deployment of the reviewed U-OPTI branch, on
**IR** and **KH** independently:

```bash
python3 -B /PATH/TO/REVIEWED/U-OPTI/modules/smite-stage15-web-approval-fetch.py
```

This is a *placeholder path*, not a command to run now. The host must have
short hostname `ir` or `kh`, root access, amd64 and enough private disk
space. The script fetches **only** the immutable ZIP from the pinned GitHub
Release URL; verifies ZIP SHA256, manifest SHA256, source commit, schema,
preview-disabled flags, file member list and each inner archive checksum and
image ID; then atomically caches ZIP and images under
`/var/lib/u-opti/smite-stage15-web-approval-images/<source-SHA>/`.
It re-verifies an existing cache, refuses unsafe files and symlinks, and
holds on mismatch. It never calls Docker, Compose, systemd, Nginx or a route
executor. Every success prints `PREVIEW_ACTIVATION_ALLOWED=NO`.

The build's manifest asserts:
`signed=false`, `registry_digest_verified=false`,
`runtime_security_verified=false`, `activation_allowed=false`.
These flags are deliberately REQUIRED by the cache-only verifier.
**Successful fetch is NOT sufficient to apply these images to running
Node or Panel containers.** A separate, individually reviewed migration
plan must first address live signed replay, existing leases, independent
attestation keys, current Compose overlays, new UI build-time Origin flag,
rollback image continuity, maintenance interruption and physical Passkey E2E.

## Safety and validation

Offline negative tests:
`python3 -B tests/test-smite-stage15-web-approval-fetch.py -v`.
A separate GitHub workflow runs syntax and integrity checks.
Do not use the legacy `U` image-upgrade menu on running 45121/38658/28897
routes. Do not recreate the IR FRPS owner, KH FRPC children, Node identity,
or signed Replay. Grandoptical is excluded.

### Acceptance of priority 1

1. Same exact ZIP moved from expiring Actions artifact to pinned prerelease,
   with verified independent SHA256 and immutable tag/asset discipline.
2. Downloader CI green including tamper/ZIP traversal tests.
3. On both disposable hosts, a separate authorized **download-only** execution
   returns `STAGE15_WEB_APPROVAL_CACHE=VERIFIED` and
   `PREVIEW_ACTIVATION_ALLOWED=NO`.
4. Runtime and the three active routes are unchanged.

Only then mark image acquisition complete. **Migration and enabling Web
Approval remain distinct later gates.**
