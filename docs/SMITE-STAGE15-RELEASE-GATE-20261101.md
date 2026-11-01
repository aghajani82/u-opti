# 2026-11-01 test candidate and stable-release gate

## Pinned starting points and field evidence

U-OPTI #74: `f67888439180dd2651dd25434bfe3e883d513cb6` (22 successful checks).
Smite #41: `aec8a5f7e7a91a9e59fd968ef0f7570fdd995d57` (13 successful checks).
These were refreshed before preparation. This document is not final production approval.

Operator reports four active FRP children, including `FRP-IR-KH-45122` and
`/45122/store`; Signed KH Inventory, G (`ROOT_GRANT_APPROVED`), publication
and v2rayN VLESS/XHTTP succeeded. This is operator evidence, not a live probe
performed during preparation. No commands were run on IR, KH or Grandoptical.

## Candidate scope

- Exact pinned Smite frontend build with optional approval origin explicitly empty.
  Persian XHTTP guidance and visible signed-listener Verify success are included.
  Verify is not proof of end-to-end VLESS/XHTTP traffic.
- Standalone UI-only transaction helper, opt-in ZIP, manifest and SHA-256;
  no default installation, image replacement or Panel/Node restart.
- Tunnel Management always prompts IR/KH first. Trusted root-owned local
  standard-mode state must match; recognized IR/KH hostname conflicts are refused.
  Role is rechecked before dispatch and every guided selection.
- FRP guided screens provide IR Panel/Gateway/Owner/Child/XHTTP-G-Publish and
  KH Node/Sanaei/Inbound/FRPC/Inventory steps, Next/Back/Status and existing G.
  PASS is explicitly limited to observed local process/container state. Signed
  inventory, leases and publication are HOLD until checked in existing tools.
  Navigation never replays setup. Original FRP setup remains under Advanced;
  the separate old RC2 option 4 and Stage15 recovery menus are unchanged.

The wizard is navigation for an already provisioned runtime, not a newly
qualified unattended installer. Fresh hosts without trusted role state HOLD
and must use the existing reviewed Smite setup first. There is no safe new
machine-readable combined signed status source here; do not manufacture PASS
from the four-tunnel report, stale journals or local process presence.
This limits readiness for a general-user stable installer.

## Required separation before a stable merge

The full current PRs must NOT be merged indiscriminately:

| Scope | Candidate disposition |
| --- | --- |
| U-OPTI root-review numeric approval and main-menu G shortcut | Retain with expiry/signature/TOCTOU/replay tests |
| New role navigation and UI transaction | Test candidate only; fifth-tunnel/operator gate pending |
| Existing FRP/XHTTP/owner/child and signed pairing foundation | Preserve; qualify against chosen stable base separately |
| Smite Persian XHTTP and Verify success UX | Include only reviewed frontend hunks |
| Smite approval attestation/runtime-evidence Node additions and opt-in approval UI | Exclude from default stable delivery |
| U-OPTI Secure Web Approval, Passkey, queue/evidence/bootstrap/service/lab modules | Exclude from default stable delivery |
| U-OPTI Root Broker web-approval opt-in hook | No new changes here; exclude optional hook when extracting console-only stable scope |
| Download-only preview/migration-gate menu entries | No deployment authorization; keep out of beginner stable installation path |

PR #74 changes 57 files before this candidate and includes experimental service
and lab modules. PR #41 changes Node attestation routes as well as frontend.
A selected-hunk stable branch and its complete CI are still required after the
field test. No stable version was bumped and neither PR was merged. Trial
packaging uses `smite-ui-aec8a5f7-trial-v1`; it is not a new production image.
Backhaul is not required by the new FRP guided path.

## Historical archive (not current images)

Separate prerelease: https://github.com/aghajani82/Smite/releases/tag/archive-stage15-reviewed-8edbd403-v1

Source artifact `12960674420`, successful preservation run `41020816370`,
original source `8edbd4032ae657fe2bb38cd9b3290de5f1e07a54` and original build
run `40921424209` were verified. No archive/image was rebuilt.

- Outer ZIP SHA-256: `55a4f55ebe6f14929c65fb05da96b60ea49f58480b3db9a46bf23c1395273575`
- Original inner ZIP SHA-256: `d250b0fd27ae362bc4008b9e62208f94ae92fb71273d66bee83c9bcdcd1f75d9`
- Archive manifest SHA-256: `5f909e4fa5c7b3428eaa4e33a4024ea6740fec828388762c3765a590c4267f1d`

Release assets contain both exact ZIPs, original image manifest, archive manifest
and SHA256SUMS. All uploaded digests were verified before publication. Large
files are release assets, not Git history. This archive is prerelease/non-latest,
independent of current images. The first workflow uploaded a draft then failed
on a tag lookup; recovery validated the existing draft by ID and published it
without overwriting or uploading replacement assets.

## Admission for fifth-tunnel test

See [UI transaction runbook](SMITE-STAGE15-UI-TRIAL.md). Preflight/Backup/Apply/
Verify/Rollback are prepared; live approval has not been given. Static rollback
never restores an old lease/grant/replay database. Mounted or different backend
layouts, container identity changes and static drift fail closed. Legacy Stage15
image upgrade is not used. If admission fails, stop; no Panel migration fallback
is authorized or implemented by this trial.

Before approval: CI including disposable Docker serving must pass; preserve four
working-client baselines and provider console/snapshot access. After approved
Apply: verify Persian UI, visible Verify result, four old clients, fifth child,
G and a fresh publication request followed by real v2rayN traffic. Record
port/path, timestamps, result and any rollback. Only then prepare final release
readiness and seek explicit merge approval.
