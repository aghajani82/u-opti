# Proposed Smite RC.2 — foreign signed pairing release admission (review only)

> **STATUS: HOLD — NO TAG, NO GHCR PUBLISH, NO MERGE, NO HOST CHANGES.**
>
> Proposed version **`v2.0.0-rc.2`** is a *review label only*, not a
> created tag or authorized release. All live IR/KH services remain on the
> previously reviewed RC.1 image pair. Do not substitute local CI image IDs
> for immutable signed GHCR digest references.

## Frozen source evidence, 2026-10-23

| Scope | Immutable source / CI | State |
|---|---|---|
| Smite [Draft PR #18](https://github.com/aghajani82/Smite/pull/18) | HEAD `31543e2e81ea635b4eaab87f606125b4e4dd22e1` | 9/9 exact-head GitHub Actions **SUCCESS** |
| U-OPTI [Draft PR #48](https://github.com/aghajani82/u-opti/pull/48) | HEAD at this review began `0485eb16b77ca871478e733358e52c1c359676df` | CI run [39938276746](https://github.com/aghajani82/u-opti/actions/runs/39938276746) **SUCCESS** |
| Smite Stage15 | [run 39937249960](https://github.com/aghajani82/Smite/actions/runs/39937249960), source `31543e2e81ea635b4eaab87f606125b4e4dd22e1` | Two unpublished images and offline manifest, checksum verification, **NOT signed registry images** |
| Smite source/current GHCR pair | `modules/smite-field-trial-candidate.json` points to RC.1 source `289f99cae8c53ba7d5b8e427bca19e5c04ebba8a` | Historical *nonactivating* record; does **not** contain KH prefix fix |

See [PR18 offline image evidence](SMITE-PR-HEAD-OFFLINE-IMAGE-EVIDENCE.md)
for the Stage15 ZIP and `stage15-images.json` distinct checksums and
artifact retention. These are runner-reported checksums, **not independently
downloaded and verified archive bytes**.

## Technical review — already evidenced, not live activated

- Real **IR → KH** public-CA TLS/443 transport succeeded through the
  operator-managed `/smite-node/<opaque>/` Nginx prefix:
  `HTTP 200`, `TLS_VERIFY=0`, response uniquely identifying
  `{"status":"ok","service":"smite-node"}`.
- With KH Node still `paused + strict`, **unsigned** request through the
  managed prefix returned `503` (authentication unavailable), while the
  unprefixed `/api/agent/status` was `404`. These show no successful
  anonymous Agent request, **not** completion of signed pairing.
- Smite PR18 repairs Panel signed transport to route through an independently
  approved hostname and exact prefix, while signing the Node's canonical
  `/api/agent/*` target and original bytes; strict negative URL tests pass.
- U-OPTI PR48 adds opt-in distinct IR approval and KH signed runtime
  admission/paused rollback workflows; **these have been tested in CI** but
  not used on the live two-host pair.

## Non-negotiable release gates, in order

1. **Review/merge authorization**: operator reviews PR18, outstanding code
   security semantics, optional changes and separate IR/KH backup recovery.
   Freeze one reviewed Smite commit. No release tag before review.
2. **Candidate publication authorization**: choose a unique new candidate
   tag (currently proposed `v2.0.0-rc.2`) pinned to that exact Smite commit.
   The existing `.github/workflows/publish-images.yml` requires manual
   `workflow_dispatch`, the actual existing tag, exact source SHA,
   repository owner actor and explicit publish consent. This is **not**
   an automatic part of the 9 passing workflows.
3. **Two immutable signed registry digests**: publish both `smite-panel`
   and `smite-node` from that one tagged source; verify each keyless Cosign
   certificate identity, Github Actions publisher identity, workflow source
   claim, image digest and matching role; independently verify the
   `registry-pair.json` SHA256. Reject a mixed-source pair or mutable tags.
4. **U-OPTI exact pair integration**: update the *nonactivating* candidate
   manifest to both **new** verified digests/source/tag. Reconcile the KH
   `_FOREIGN_NODE_IMAGE` pin in `smite-node-pairing.py` (currently RC.1)
   to the independently admitted **new Node** digest before a new KH Node
   is ever used. Preserve `activation_allowed=false`,
   `release_approved=false` until separate authorization. U-OPTI requires
   a new CI pass at the final SHA after these changes.
5. **IR-only staged Panel upgrade**: snapshot, verify current local signed IR
   Node and `smite-panel` before/after, Nginx config and rollback.
   Never replace the active Panel image merely to see whether a registry
   candidate exists. Ensure the new live Panel supports prefix-pinned HMAC.
6. **Admin-reserved KH identity**: on the Panel create a unique pending
   `foreign` Node UUID/name through its authenticated reservation flow.
   Confirm it remains `pending`/`reserved_for_pairing`; install only its
   reviewed exact foreign HTTPS/443 origin/prefix in the private
   `approved-origins.json`. Never approve Node-supplied legacy metadata,
   or print secrets in logs / PR comments.
7. **Secure one-time KH enrollment**: only after Panel trust, issue a
   short-lived single-use code via the authenticated admin interface;
   redeem over TLS with public CA verification and no proxies/redirects;
   store private identity and replay on durable approved mounts.
   **Never share the code or HMAC key in chats, CI, or version control.**
8. **KH signed runtime trial**: validate the new exact signed Node image
   digest, scope the Compose recreation to `smite-node`, preserve Sanaei
   `3xui-01`, unchanged XHTTP Nginx routes, FRP and Backhaul.
   Verify successful signed KH → IR registration, IR → KH HMAC Agent GET,
   replay rejection, revoked/missing key rejection and no anonymous fallback.
   On failure keep the Node `paused + strict`, verify rollback, and retain
   replay/identity for manual reconciliation. Recheck both hosts after reboot.
9. **Explicit separate release decision**: operator inspects full audit and
   authorizes (or refuses) production merge/release. A successful trial is
   **not** automatic permission to promote main or stable defaults.

## Gaps to qualify before the first live pairing

- The existing historical `v2.0.0-rc.1` GHCR pair cannot contain the new
  PR18 Panel fix; current KH pin is intentionally **fail-closed** for a new
  digest. The first reviewed new digest pair does not yet exist.
- Existing IR Panel is still on the previous signed RC.1 image. Old Panel
  has no approved foreign prefix routing; U-OPTI's IR foreign approval guard
  must reject activation until a reviewed Panel image is deployed.
- Verify the actual live Panel Node-reservation record and trusted origin
  mount without exposing the values of credentials, pairing codes or keys.
- Live KH ↔ IR signed acceptance, blocked public TCP/8888 from WAN,
  disallowed unprefixed Agent access, dynamic inbound preservation and
  shutdown/reboot/rollback have **not** been qualified for the new pair.
- Source CI and offline image checksum tests **cannot establish** GHCR
  registry signing, production usability or operator approval.

**Next allowable step without explicit new publication approval:**
review the proposed RC.2 source/contract, identify any remaining preflight
gaps, and collect **read-only** host preparedness evidence. **Do not create
a tag or run `publish-images.yml` until explicitly authorized.**
