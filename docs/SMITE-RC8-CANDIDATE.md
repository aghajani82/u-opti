# RC8 signed candidate — no deployment authorization

The selected registry pair is the original `registry-pair.json` from the successful
[Smite publisher run 42600830571](https://github.com/aghajani82/Smite/actions/runs/42600830571).
All four publisher jobs succeeded. Artifact ID: `13665064301`; name:
`smite-registry-pair-b7168f09bf236c9400adbeeaa9446a1a18293fa6`.

- Tag: `v2.0.0-rc.8`.
- Exact source/peeled commit: `b7168f09bf236c9400adbeeaa9446a1a18293fa6`.
- Original ZIP SHA256: `32b9646bf4520c9189f4fa7415e78ed3a4847f9289395561bb14febcb6ec72f2`.
- Independently computed manifest SHA256, including its final newline:
  `ed0fc73534d61f6bf9fd0d4710385bf8c336d417c9a2401ba8e13c9995267576`.
- Panel: `ghcr.io/aghajani82/smite-panel@sha256:7397c1bd129893640f02e168420cefdd78171241dc1973973e5cfbad9197b160`.
- Node: `ghcr.io/aghajani82/smite-node@sha256:164991d2380f6bb334f05da0783b34c75e87746625d7f6b2e58b21f70187ff8b`.

[Independent verifier run 42601317589](https://github.com/aghajani82/Smite/actions/runs/42601317589)
succeeded using the existing frozen U-OPTI verifier and real Cosign v3.0.6:
`INDEPENDENT_REAL_COSIGN_GATE=PASS`, `DEPLOYMENT_AUTHORIZED=NO`.
The current U-OPTI verifier was also run against both real RC8 registry signatures
with installed, officially verified Cosign v3.0.6 and the existing pinned trust
root; both digest/source/role checks passed. Offline fake-Cosign tests are separate
refusal/regression evidence, never a substitute for those registry verifications.

## Candidate versus installed RC7

The nine-key selected candidate keeps `activation_allowed=false` and
`release_approved=false`. Existing Backhaul option 2 uses its exact RC8 manifest,
source, tag and Node digest for read-only candidate review. An installed RC7 Node
does not match this candidate and cannot be treated as an installed RC8 Node.
The separate `verify-rc7-bundle` check still reports historical RC7 inventory.

`modules/smite-rc7-registry-pair.json` preserves the prior manifest byte-for-byte
(SHA256 `58bebfc605a5c1a64cf02ce38e6397dbcdae5f1c3289a01952f361b6a8aa660e`).
The existing RC7 fresh installer, retained metadata enrollment/rollback, and RC7
runtime qualification keep using their historical pins. Both installer and
updater ship this preserved file. The existing CI workflow authenticates RC8
and RC7 separately, then retains its original RC7 runtime/UI/recovery tests.
No RC8 installation path is enabled by selecting the candidate. Missing installed
Cosign for RC8 is HOLD; the temporary downloader remains RC7-only.

Smite main at review was `5e7a289071e446345ac27e4255994daf3446430a`; its later UI
PRs #55–57 are not part of the specifically approved RC8 source. U-OPTI's newer
RC7 UI bundle and its image guard remain unchanged. RC8 publication must not be
described as including those later UI changes or qualifying that UI updater for RC8.

`LIVE_IR_CHANGED=NO`, `LIVE_GRANDOPTICAL_CHANGED=NO`, `FRP_TUNNELS_CHANGED=NO`,
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`, `DEPLOYMENT_AUTHORIZED=NO`.

Ubuntu 26.04.1 compatibility, provider console access, actual restore evidence,
and any coordinated Panel/Node lifecycle or maintenance window need a separate
live-deployment mission. GitHub runner checks do not establish VPS readiness.
