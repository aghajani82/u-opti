# Smite RC2 — Lab-trial admission and signed preview provenance

**Status: Preview provenance PASS; live lab activation HOLD.**  
**Scope:** only disposable IR/KH VPS; `Grandoptical` is permanently excluded.  
**Code branches:** Smite Draft PR #20; U-OPTI Draft PR #48. No main merge, tag publication or service restart without separately approved release and rollout gates.

## Pin exact accepted *preview*, not an authorized release

- Smite reviewed preview source commit: `ac67625c0fde00392a9142801b55ee61f296c86c`.
- Final exact-head GitHub Actions run: [Stage15 #40196400521](https://github.com/aghajani82/Smite/actions/runs/40196400521), part of **13/13 passing workflows**.
- Three-file preview ZIP artifact: `smite-stage15-offline-images-ac67625c0fde00392a9142801b55ee61f296c86c`; artifact ID `12600091559`; uploaded ZIP SHA256 `153160ba514628c5bc2d7bb4dcb8e453308fbfd36896c6b38c6d14a5ebbaeddd`; Manifest `stage15-images.json` SHA256 `70719798b01cd17aeb7c90d1651136c98f2fac47c3fcf1cb6bbd01fcf52be119`; expires 2026-10-28T13:12:27Z.
- [GitHub SLSA file attestation #59620104](https://github.com/aghajani82/Smite/attestations/59620104) and [Sigstore Rekor entry 3461683354](https://search.sigstore.dev?logIndex=3461683354).
- In the **same checked-out workflow source**, the post-signing `gh attestation verify --repo aghajani82/Smite --signer-workflow aghajani82/Smite/.github/workflows/stage15-offline-image-bundles.yml` gate independently validated the signed **Manifest, Panel archive, and Node archive** one by one. Job output: `GITHUB_CRYPTOGRAPHIC_PREVIEW_VERIFICATION=PASS`. This checks signature, file digest and signer identity, but does **not** authorize execution on any VPS.

The preview manifest enforces `signed=false`, `registry_digest_verified=false`, `runtime_security_verified=false`, `activation_allowed=false`. **Never edit or override these values.** This artifact is not a signed GHCR image release. Older ZIPs and `stage15-local` Docker tags on IR/KH are superseded and must not be activated.

## Admission boundaries — mandatory BEFORE live rollout

1. **Independent release trust**: obtain and verify separate immutable **release-candidate** Panel+Node image digests with approved publisher provenance and Cosign, or an explicitly reviewed lab-only equivalent release contract. Merely attesting an offline preview does not satisfy this condition. Publishing the existing GHCR/tag workflow requires the owner's separate explicit consent; never create tags or push publicly without it. **Current status: HOLD.**
2. **Operator authorization**: explicitly approve scope, pinned image pair, rollback strategy and possible short `45121` outage before container replacement. No global ApplyAll, no automatic reapply and no implicit approval from prior preflight PASS. **Current status: HOLD.**
3. **State continuity**: independently re-check IR/KH provider snapshots, private backup consistency and recency, Compose image IDs/mounts, Panel SQLite migration plan (`frp_proxy_leases` uniqueness), root-only Node identity/enrollment marker and persistent Replay DB. Do not restore stale replay snapshots without approved quarantine/recovery. **Existing preflight PASS is not post-upgrade proof.**
4. **Startup safety**: verify exact candidate code includes the signed+managed FRP Panel startup and timer auto-reapply guards. Ensure disabled Panel-side FRP comm/server and any legacy FRP startup path cannot claim IR `127.0.0.1:7000`. Preserve only one owner `trial-frp-45121`.
5. **Controlled rollout**: IR Panel first, then KH Node, then IR Node, with **independent health/status, signed owner proof and `45121` VLESS client traffic** verified after each step. IR Node replacement necessarily restarts FRPS; brief interruption is possible. Roll back only by exact old image IDs plus the documented consistent state plan. Never touch Grandoptical.
6. **Second child after first port recovery**: only signed KH child Apply for `49328` under the same IR FRPS owner; require IR loopback `49328` listener proof before U-OPTI Nginx guard publishes `/49328/sso` behind 443. Verify actual VLESS/XHTTP traffic through both `45121` and `49328`, no second FRPS, no non-443 public listeners.
7. **Close-out**: reboot/rollback exercises, collision and concurrent child Remove/Apply negatives, no secret exposure, operator UI review. PRs remain Draft and main stays untouched until the owner gives final approval.

## Safe current operator action

No IR/KH command is required while the candidate release trust gate is HOLD. Preserve the current working `45121` installation and existing snapshots/backups. The GitHub preview may be audited or independently verified, but **not deployed**. No Grandoptical changes ever.
