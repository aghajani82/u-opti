# Smite Preview Pair — exact PR-HEAD build evidence (2026-10-20)

**Central closeout:** [Issue #47](https://github.com/aghajani82/u-opti/issues/47) ·
[U-OPTI Draft #48](https://github.com/aghajani82/u-opti/pull/48) ·
[Smite Draft #16](https://github.com/aghajani82/Smite/pull/16).

**Classification: VERIFIED EPHEMERAL CI PREVIEW, NOT APPROVED OR RELEASED.**

## Root-cause fix: wrong source identifier in older images

Previous successful Smite Stage15 image build
[Actions run 39313614098](https://github.com/aghajani82/Smite/actions/runs/39313614098)
produced artifact `smite-stage15-offline-images-0fb747b0911432503643ad83efc1e8247b15aa6e`.
Runner logs show checkout of `refs/remotes/pull/16/merge` at **synthetic
merge commit `0fb747b0911432503643ad83efc1e8247b15aa6e`**,
not the Smite PR branch HEAD `3751aeda6f946e5e5624e5e89ab1ce554fec4460`.
The earlier manifest used `GITHUB_SHA` which on pull requests is a synthetic
merge checkout. This is not proof that the old image bytes were unsafe;
it is *wrong evidence for claiming an exact PR-head build*.

In **the existing Smite Draft #16, without a new PR**, the
`.github/workflows/stage15-offline-image-bundles.yml` workflow now:

1. Checks out the **exact PR-head** `github.event.pull_request.head.sha`
   (or `github.sha` for non-PR triggers), never implicitly the PR merge ref.
2. Verifies `git rev-parse HEAD == SMITE_BUILD_SOURCE_SHA` **before building**.
3. Builds **both** Panel and Node from that one exact reviewed checkout.
4. Writes `SMITE_BUILD_SOURCE_SHA` into the offline manifest,
   verifies that SHA against the generated manifest, and names the artifact
   using this same source SHA. A regression test in
   `tests/test_stage15_offline_bundle.py` enforces these contracts.
5. Continues to explicitly refuse GitHub Container Registry pushes, GitHub
   releases, production deployment and IR/KH writes.

## New real GitHub Actions evidence

- Smite Draft #16 reviewed HEAD / exact checkout:
  `995977d0ac9be69b6c9e3d3c257c5cd8c1abe220`.
- [Successful Stage15 Panel+Node offline image workflow run **39378799692**](https://github.com/aghajani82/Smite/actions/runs/39378799692),
  source checkout printed
  `SMITE_BUNDLE_SOURCE_COMMIT=995977d0ac9be69b6c9e3d3c257c5cd8c1abe220`
  and `BUNDLE_PR_MERGE_SHA_UNUSED=YES`.
- Archived **both** offline preview images under
  `smite-stage15-offline-images-995977d0ac9be69b6c9e3d3c257c5cd8c1abe220`,
  artifact ID **12244433473**, 408,736,100 bytes in uploaded ZIP.
- GitHub Actions artifact ZIP digest (NOT the image archive hashes):
  `sha256:767f600e8d39b3882ff8d091f1d731d9b9f0f402dd613d464ea349b0743e1f58`.
- `stage15-images.json` SHA256, copied separately from the successful
  build job logs (this is the **manifest** checksum, NOT ZIP digest):
  `d486dd2075b1187d735b50c18538a1002f066984962080474f3f4be6ae1e19ab`.
- The build logged
  `OFFLINE_PREVIEW_ARCHIVES=CHECKSUM_VERIFIED`,
  `IMAGE_REGISTRY_PROVENANCE=UNVERIFIED`,
  `LIVE_DEPLOYMENT=BLOCKED`, `NO_GHCR_PUSH=YES`,
  `NO_RELEASE_TAG=YES` and `NO_IR_KH_INSTALL=YES`.
- Artifact reported expiration: **2026-10-23T06:11:22Z**.
  Do not keep offering an expired artifact as downloadable. The hashes,
  source and CI run remain a reference for future reproducible builds.

**Caution:** This confirms a coherent paired source built inside a
disposable CI runner, with offline archive checks and tested image
smoke/first-boot gates. It is NOT a signed supply-chain attestation,
not a published registry digest, not proof that an installer can
safely migrate Smite v0.1.7 to this candidate, not a cross-VPS
functional qualification, and not an independent verification of the
400 MB archive bytes by U-OPTI or the assistant.

## U-OPTI compatibility

In the SAME ongoing U-OPTI Draft #48 branch, the two strict-source
FastAPI/replay and actual Nginx/443 integration jobs now checkout precisely
the **new Smite source SHA**
`995977d0ac9be69b6c9e3d3c257c5cd8c1abe220` instead of the old
`3751aeda6f946e5e5624e5e89ab1ce554fec4460`.
Historical interoperability jobs pinned to older Smite commits are
**not** silently changed (they intentionally test prior interfaces).
The run/HEAD CI for this change must be verified separately.

Existing read-only U-OPTI
`modules/smite-stage15-bundle-verify.py` expects the caller to provide
the **independently sourced**
`--source-sha 995977d0ac9be69b6c9e3d3c257c5cd8c1abe220`
and
`--manifest-sha256 d486dd2075b1187d735b50c18538a1002f066984962080474f3f4be6ae1e19ab`
when examining the uncompressed artifact bundle. It validates both
archive checksums and sizes from that manifest. An internally
consistent manifest alone is NOT independent trust. Do not import,
tag, start or install the images under the guise of verification.

## Still blocking final release / next actions

1. Explicitly reviewed and approved immutable U-OPTI+Smite
   source/image release mapping, durable image distribution,
   digest/signature provenance and retention. No auto-switch
   of the default stable `zZedix/Smite v0.1.7` image pair.
2. Complete operator-approved **strict first pairing + durable replay
   DB bootstrap**, trusted persistence/mount ownership, secure key
   rotation/quarantine and safe backup/restore, all fail closed.
3. Eliminate actual Backhaul→FRP baseline dependency, preserve
   dynamic selected KH inbound port/path, and validate beginner IR/KH
   setup and engine independence.
4. With separate operator approval only: disposable snapshot-backed VPS
   real-network/reboot/power-loss admission, regression matrix,
   explicit production release/merge decision.

**Status:** `INSTALL_ALLOWED=NO`,
`ACTIVATION_GATE=HOLD`, `MAIN_MERGE=NO`,
`RELEASE_PUBLISH=NO`, `IR_KH_UNCHANGED=YES`.


---

## New independent PR18 KH signed-gateway candidate (2026-10-23)

This section supersedes historical **source/build recency** statements above,
**not** the unchanged fail-closed release/activation policy. PR16 was merged;
the new in-progress reviewed signed-KH-gateway source is Smite
[Draft PR #18](https://github.com/aghajani82/Smite/pull/18).

### Exact-source CI outcome

- Reviewed Smite PR18 branch HEAD: `31543e2e81ea635b4eaab87f606125b4e4dd22e1`.
- Nine exact-head workflows finished **SUCCESS**:
  [Stage14 unpublished contract, run 39937249980](https://github.com/aghajani82/Smite/actions/runs/39937249980);
  [Panel Signed NodeClient, run 39937250022](https://github.com/aghajani82/Smite/actions/runs/39937250022);
  [Signed Agent strict commands, run 39937250314](https://github.com/aghajani82/Smite/actions/runs/39937250314);
  [Stage12 approved origins, run 39937249999](https://github.com/aghajani82/Smite/actions/runs/39937249999);
  [Admin API security, run 39937250092](https://github.com/aghajani82/Smite/actions/runs/39937250092);
  [Stage10 unpublished auth images, run 39937250230](https://github.com/aghajani82/Smite/actions/runs/39937250230);
  [Stage11 FRP/Backhaul, run 39937250013](https://github.com/aghajani82/Smite/actions/runs/39937250013);
  [Panel trial build, run 39937250089](https://github.com/aghajani82/Smite/actions/runs/39937250089);
  [Stage15 exact-source offline pair, run 39937249960](https://github.com/aghajani82/Smite/actions/runs/39937249960).
- Stage15 runner confirmed
  `PANEL_AND_NODE_IMAGE_REVISION=EXACT_SOURCE_SHA`,
  `PANEL_NODE_IMAGE_IDS_DISTINCT=YES`,
  `IMAGE_SOURCE_SMOKE=PASSED` for both roles and
  `OFFLINE_PREVIEW_ARCHIVES=CHECKSUM_VERIFIED`.
- Output artifact:
  `smite-stage15-offline-images-31543e2e81ea635b4eaab87f606125b4e4dd22e1`,
  artifact ID `12493499940`, uploaded ZIP size `372997785` bytes.
  Build log artifact ZIP SHA256:
  `c4d08680cd381b63306a6c62d1b0edd29ca282d1205425e7a5c6b3e17cdf3773`.
  **Separately** the SHA256 of `stage15-images.json` reported by the runner:
  `af317dfb71d2c39d505627397f373eaca25065512fa17b30660d6d04be60055a`.
  **These are different objects.** Values are copied from GitHub Actions
  logs, not a locally independently downloaded/verified ZIP.
- The Panel trial image workflow uses `push: false` and does not deploy.
  Stage15 reports `IMAGE_REGISTRY_PROVENANCE=UNVERIFIED`;
  the images are **unpublished offline previews**.

### Remaining supply-chain and live rollout gate

The older **recorded, non-activating** registry pair in
`modules/smite-field-trial-candidate.json` is `v2.0.0-rc.1`,
Smite source `289f99cae8c53ba7d5b8e427bca19e5c04ebba8a`.
It is not the new PR18 Panel source; neither its Panel nor Node digest
may be claimed to include the KH gateway-prefix fix.

Before enabling a foreign signed Node:

1. Review and merge Smite PR18 **only after explicit operator release review**.
   The workflow `.github/workflows/publish-images.yml` is separately
   `workflow_dispatch` gated by owner consent, an exact existing tag
   and matching 40-character reviewed source commit; CI success does
   **not** invoke it automatically.
2. Publish and independently verify **both** new Panel and Node immutable
   registry digests, Cosign identity/source/role claims, signed tag, external
   manifest SHA256 and exact source mapping; keep activation flags false.
3. Prepare a reviewed U-OPTI candidate digest-pair update.
   **Do not retain the earlier hardcoded KH Node digest in
   `modules/smite-node-pairing.py` if deploying a new Node**: its
   `_FOREIGN_NODE_IMAGE` guard would correctly HOLD.
4. Validate fresh IR-only Panel upgrade, preserved local signed Node,
   HTTPS/443 foreign approval, pending reserved foreign UUID/name,
   KH identity/replay enrollment, signed two-way HMAC status and
   safe paused rollback. Preserve existing KH Sanaei XHTTP and FRP/Backhaul.
5. Only after the above passes with snapshot-backed disposable IR/KH,
   explicitly consider Draft PR #48 and a release approval.

**CURRENT STATE:** `SMITE_PR18_CI=PASS_9_OF_9`,
`OFFLINE_PAIR=BUILT_NOT_PUBLISHED`,
`REGISTRY_PAIR_SIGNED=NOT_PROVEN`,
`IR_KH_CHANGES=NONE`, `PAIRING_ACTIVATION=HOLD`,
`MAIN_MERGE=NO`, `PRODUCTION_RELEASE=NO`.
