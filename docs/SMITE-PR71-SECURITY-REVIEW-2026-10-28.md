# Stage15 installation and PR71 security review — 2026-10-28

Baseline U-OPTI: `ede7405d114d1e9a0af0cc83a2c5f867c2be7423`.
Baseline Smite main: `536f723d088540cbec5064037532d48c1579e554`.
Immutable Stage15 image source: `4e16633a304db6c03f7f2911cc7d77213b0c4ec1`.
No VPS, production host, DNS, service, firewall or tunnel was accessed/changed.

The two attached task documents were read in full. The uploaded ZIP was not
available in this session. Instead, GitHub artifact 12714389112 was obtained
independently and its complete bytes matched the previously recorded ZIP hash
`2bda0c80aa77ce6fa6bd1af0a4ed0d8fccfad670915dfd2f56a6120b08d19a71`.
It contains only two Docker image archives and stage15-images.json: an image
preview bundle, neither a patch nor a complete installer. This does not prove
that the unavailable user upload is byte-identical.

## Findings and minimal corrections

Line references in this table are to the **baseline commits above**, so future
edits do not obscure the original defects. Severity concerns the affected path;
it is not evidence of exploitation on either host.

| Severity | Baseline file / location | Failure scenario | Correction |
|---|---|---|---|
| High | Smite `panel/app/frp_server.py:74`, `:124` | Starting the Panel FRPS path logs token-bearing YAML; failure echoes raw child output into application logs/errors. | Smite PR #38 removes both disclosures, keeps exit-code diagnostics, restricts config/log to 0600 and rejects leaf symlinks. Old Stage15 images still contain the old code. |
| High | U-OPTI `modules/smite-stage15-frp-host-executor.py`, `runtime():199` | Matching mount destinations/RW flags are accepted even when identity or Replay bind source is different. The checked host inode then does not prove the running Node uses that database. | Exact bind source/type and in-container identity/Replay path checks; validate sources in effective Compose before any restart. |
| High | U-OPTI same file, `restore():407` | Rollback can recreate a drifted current container without first checking its security configuration; journal state is changed only after deleting the manifest. | Check current runtime policy before mutation (unhealthy is recoverable only if configuration matches); durably record RECOVERING before deletion. |
| Medium | U-OPTI same file, `update_record():345` | Power loss leaves record.new; subsequent recovery refuses to create it and cannot advance. | Validate/remove only the private scratch file and rewrite it. Refuse symlink, unsafe journal mode and unknown entries. Tests interrupt before rename and after manifest removal. |
| Medium | U-OPTI same file, `load(...smite-rc2-frp-bundled-enrollment.py):48` | Repository tests import a module that is absent from a first install. The deployed helper fails before its safety gate. | Keep the existing bounded HMAC/replay probe self-contained. Test CLI import from exactly the install manifest, not repository contents. |
| Medium | U-OPTI `u-opti`, `BACKUP_FILES:1275` | Compose plan and host executor are downloaded/updated but omitted from the backup list. | Add both; enforce every updated module participates in backup. |
| Medium | U-OPTI `modules/smite-managed-frp.py`, `unpack():96` | Archive is hashed, then reopened by pathname; a replacement between operations may be extracted. | Hash and parse the same bounded immutable byte buffer. Replacement-race regression. |
| Medium | U-OPTI host executor, `file():85` / `run():162` | Leaf-only no-follow permits ancestor symlink traversal; ambient Docker context may redirect commands. | Check owned non-writable ancestry (root-owned sticky shared ancestors allowed), require private journal 0700, bind execution to local Unix Docker socket and reject ambient context overrides. |

No Critical finding was established by this scoped review. This is not a claim
that every executable path in either repository has been audited.

## PASS evidence and limits

- FRP official v0.71.0 archives for **both amd64 and arm64** were downloaded and
  hashes independently matched the committed pins; both binaries are checked
  against the same archive bytes and ELF machine. Not merely a version string.
- Unknown Stage15 images remain rejected. Existing RC.2 pins remain unchanged.
- Replay, identity and signed Compose files are not removed or rewritten by
  the FRP transaction. Protected inode/digest tests and negative tests exercise
  drift; actual HMAC is tested separately in the immutable-source CI lane.
- Root, explicit field-trial flag, IR/KH hostname, role confirmation, snapshots
  and console confirmations remain required. No novice-menu activation added.
- Recreate uses base + signed security + FRP overlay; rollback uses base +
  signed security. Node command remains loopback 127.0.0.1:8888, host port
  bindings are rejected, WSS remains off and no FRPS owner/tunnel is created.
- FRP files remain separate from Backhaul/Rathole. Nonempty engine state and
  saved tunnels still HOLD; cleanup no longer removes an untracked parent.
- Host tests use real temporary root-owned filesystem paths and mocked Docker
  and signed callbacks. They are not real Docker/IR/KH tests.
- The real Docker FRP CI job now uses exact Stage15 source instead of the older
  a15c462 source. It is network-isolated and does not prove 443/WSS/XHTTP traffic.

## Remaining blockers — do not hide with new IDs or menu switches

1. Stage15 WSS/443 Node/Panel/edge activation with signed owner lifecycle and
   independent rollback acceptance is still not implemented as a complete
   beginner-wizard transaction. FRP engine READY is not transport readiness.
2. Existing Stage15 images do not include the FRPS privacy correction. A new
   reviewed build, independently established image IDs and controlled rollout
   are required before authorizing the affected Panel FRPS path. Signed KH
   pairing alone does not require replacing the existing Panel image.
3. No real two-host FRP/WSS/XHTTP client traffic, reboot, full Ubuntu clean
   installation or host power-loss test was run. Local environment has no
   Docker daemon. PR Docker tests run only on disposable GitHub runners.
4. Arbitrary interruption during an artifact write or before the initial
   complete journal may leave incomplete bytes that intentionally HOLD for
   console review. Checkpoint tests do not prove automatic recovery at every
   instruction or safe cleanup of an untrusted partial record.
5. The supplied bundle is not a fully offline OS/Sanaei distribution. Online
   apt/Docker/Sanaei dependencies are declared; they are not silently omitted
   while calling it an all-dependencies offline installer.

Issue #67 was found closed although its body explicitly requires live
acceptance before closure. It must track these outstanding gates as open.
The reviewed fixes can merge independently when their exact HEAD passes CI;
that does not authorize activation or close the end-to-end installation task.

**HOLD_WITH_BLOCKERS**
