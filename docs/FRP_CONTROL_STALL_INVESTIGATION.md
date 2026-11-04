# FRP 0.71.0 control write stall investigation

Scope: isolated investigation only. No live access or changes to IR or
Grandoptical. No production pins, binaries, images, UI, services, FRPS ownership,
tokens, pairing, grants or replay ledgers are changed by this PR. Preserve
20182, optical and nahavi. In this investigation optical is reported active by
the user; do not replay any earlier unconfirmed publication request.

## Exact source and package provenance

| Item | Verified source/pin |
|---|---|
| U-OPTI main reviewed | `4a24d1d7b4d201a02e3f1da87f4aefc789f914b6` |
| Smite main reviewed | `115f032761564a069d0aa2ca891e55d53a1c6ea0` |
| RC7 image application source pinned by U-OPTI | `9a1270b31e8d44f13d09b71ab6b9798410b09c12` |
| FRP v0.71.0 source commit (peeled tag) | `4a23aa181c1d7e28eecaa8216024ed753b9d27c8` |
| FRP v0.71.1 source commit (peeled tag) | `d8cf1800dc1abd7fda1828cab105d7a6b5a50eb1` |
| Upstream PR #5550 merge commit | `fccc7b0e9f8855882677c827a71255bc1f11d488` |
| RC7 Node OCI digest | `03ae4ca0f6d516374671fad4e32d44c13fbb46d0e4309bccb0265230d6fc4263` |
| RC7 Panel OCI digest | `180a4d1f5ba8e24ed67d9b708e53a2b8cc9ba685aeb3a88d53df46ee663ae9f8` |

These are repository pins, NOT measurements of the user's currently running
processes. The version string alone cannot prove that a running binary contains
or lacks a patch. Actual RC7 image extraction and official-binary comparisons
passed in the CI audit: Node frpc/frps and Panel frps exactly match official
0.71.0 linux/amd64 bytes. Live processes remain uninspected.

Official release archive SHA-256 (distinct from per-binary SHA and OCI digest):

| Version | Architecture | SHA-256 |
|---|---|---|
| 0.71.0 | linux/amd64 | `84f27e39f11169f7adcef8e8b70c9329de17747b1f14dad9fb95eef5682ea716` |
| 0.71.0 | linux/arm64 | `f33c293c275d8fc68c654b6fba8f10b2551d6463d09a9fc9cffb7227eae82266` |
| 0.71.1 | linux/amd64 | `1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803` |
| 0.71.1 | linux/arm64 | `8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019` |

Smite node/Dockerfile downloads a pinned upstream archive, checks its SHA,
installs BOTH frpc/frps and checks their versions. Panel installs frps the same
way. It does not build FRP from source or apply a dispatcher patch. U-OPTI
`smite-managed-frp.py` and the legacy preparer pin the same archives. The managed
path checks archive structure/ELF and records per-binary digests; RC7 enrollment
hashes the image binaries into its engine manifest. RC7 image/source verification
is separately tied to its signed release manifest and pinned image digests.

Caveat: the legacy `smite_frp_prepare_binaries` fast path trusts the existing
executable version strings rather than rehashing against the archive. Do not
confuse that with the stronger RC7 image and enrollment path. This investigation
does not modify that separate installer behavior.

## Code evidence and reachability

Primary sources:
- https://github.com/fatedier/frp/issues/5549
- https://github.com/fatedier/frp/pull/5550
- https://github.com/fatedier/frp/releases/tag/v0.71.1
- https://github.com/fatedier/frp/blob/4a23aa181c1d7e28eecaa8216024ed753b9d27c8/pkg/msg/handler.go
- https://github.com/fatedier/frp/blob/d8cf1800dc1abd7fda1828cab105d7a6b5a50eb1/pkg/msg/handler.go

0.71.0 `Dispatcher.sendLoop` discards `WriteMsg` errors. A v1 encrypted writer
can retain a one-off lower-transport error permanently, while its multiplexed
session remains usable. ReqWorkConn messages can then be accepted into the
queue without being delivered. Client reconnect waits on control termination;
a still-blocked read loop prevents that lifecycle from progressing.

0.71.1 stops sends on error, interrupts reads with SetReadDeadline where
supported, closes the failed connection once, and closes Done only after the
read loop/synchronous handler finishes. Send is still a queue operation, NOT a
delivery acknowledgement. The exact release includes the read-deadline/yamux
regression in addition to the two named tests; testing only Close would miss
this important multiplexed-stream behavior.

Both client/control.go and server/control.go construct this dispatcher with a
closable `*msg.Conn`. Shared FRPS has a separate control per client. Smite's
FrpAdapter runs one FRPC process per child and uses a shared server process;
therefore one stuck child control need not stop another child's active stream.
An owner-process restart, in contrast, interrupts all of its child controls.

## Effective generated settings (not a live configuration dump)

Smite `core_adapters.py` emits server loopback bind/proxyBind, token auth, and
client WSS/443 using `frp_gateway_config.py`. It emits loginFailExit=false and
trustedCaFile plus serverName. It does not emit tcpMux or heartbeat overrides.
The tests invoke the actual version-specific Complete methods on this omitted-
field configuration; do not infer live values merely from documentation.

Values confirmed by executing both versions' Complete methods in CI:
- wire v1; tcpMux=true on both sides; mux keepalive 30 seconds.
- client application heartbeat interval/timeout -1/-1; server heartbeat -1.
- client pool count 1. Application heartbeats are disabled by the mux default.
- failed login retries are enabled by Smite; control termination drives reconnect
  with FRP's existing bounded exponential backoff, not a fixed 8–10 minute timer.
- WSS is the outer transport. It does not bypass Dispatcher or its v1 crypto.

## Isolated test design and evidence boundaries

CI checks out exact upstream commits and uses Go 1.26.0. The official
handler_write_error_test.go is copied unchanged onto 0.71.0; the regression is
required to fail specifically waiting for failed-control closure (not a compiler
or download error). The sticky-writer test must pass on the old source. The
complete fixed msg suite runs with race detection three times, including
handler_shutdown_test.go and the real TCP/yamux timeout test. Client, server and
transport package suites also run with the race detector.

Integration uses a disposable Docker network:none container, Nginx TLS/WSS on
loopback 443, one real FRPS and two real FRPC children. All credentials are
public test fixtures, never production values. The server fault build has one
constructor seam and a test-only wrapper that injects a retained WriteMsg error
for child A. It does NOT patch sendLoop or implement a custom repair. This is
necessary for deterministic integration injection; actual encrypted-writer
retention is proven separately by the unchanged upstream regression. These
fault binaries are not published or installed.

Tests require old control stalling, fixed control reconnect without process
restart, unchanged owner PID and continued use of child B's already-open stream.
Official unmodified binaries additionally test both mixed-version combinations,
WSS certificate verification, wrong-token and wrong-hostname rejection, and
0.71.0 -> 0.71.1 -> 0.71.0 -> 0.71.1 owner replacement with clients reconnecting.
That upgrade/rollback test allows interruption: it does not claim zero downtime
or that established streams survive owner replacement. Config and token bytes
must remain identical. A corrupted archive must fail its SHA check.

## Executed results

[Successful isolated CI run](https://github.com/aghajani82/u-opti/actions/runs/41822583130/job/126549140809)
on investigation commit `eee4a28f129a3fccf7253bd29d95cd8d0a68432c`:

| Check | Observed result |
|---|---|
| Official old sticky encrypted writer test | PASS: retained write failure reproduced |
| Official old failed-control closure regression | Expected FAIL: timed out waiting for failed control connection close |
| Fixed msg suite, race detector, three repetitions | PASS, including shutdown and real TCP/yamux v1/v2 timeouts |
| Fixed client/server/transport package suites | PASS |
| Effective omitted-field settings, both versions | PASS; values recorded above |
| Shared WSS, injected sticky write error, 0.71.0 | New requests stalled; explicit lab child restart recovered |
| Shared WSS, injected sticky write error, 0.71.1 | Automatic control reconnect; same child process |
| Unaffected child in both fault scenarios | Existing stream preserved; shared owner PID unchanged |
| Official mixed client/server versions, both directions | PASS, two children through WSS/443 |
| Official owner upgrade / rollback / recovery | PASS; configuration/token bytes retained; interruption allowed |
| Wrong token / TLS hostname; corrupted archive | Rejected |
| Pinned RC7 image binary byte comparison | PASS against official 0.71.0 amd64 artifacts |

Artifacts contain sanitized results, package hashes and Go build metadata. This
workspace only ran syntax/static validation; the disposable GitHub runner ran
the Go, Docker and network-isolated integration tests. The integration injects a
sticky message-write error; it does not prove an actual mobile/VPS network event.
The independent upstream test exercises real encrypted-writer retention, and
the fixed yamux test exercises a real TCP write timeout and read interruption.

Per-binary SHA-256 calculated from the verified official release archives:

| Version | Architecture | Binary | SHA-256 |
|---|---|---|---|
| 0.71.0 | amd64 | frpc | `f79fff8de3089ec711ff8bdd4b73e00dfe491a1c3d754983c8b0f8d58c21b068` |
| 0.71.0 | amd64 | frps | `b95dee2bf29a021c562565cdf2116376b9fa7590361bd36ef57041a04d0e6654` |
| 0.71.0 | arm64 | frpc | `6e8e45fd0c7514b636fd8d049212f8a5715e8b33c412cf968988252e7a8a00f2` |
| 0.71.0 | arm64 | frps | `68263b9cab7d9a570593fd8e0593c5a4bafdd35f0dc386e9814ade063ffa6120` |
| 0.71.1 | amd64 | frpc | `35c6054d4549bbcf2f02875543895fd9e44c2aae2925f61cd8ff5a693703c28b` |
| 0.71.1 | amd64 | frps | `2322762939e66e66850bbc9103b6d73fec39e83bd8ad6c71ebeeb120d56d6ab3` |
| 0.71.1 | arm64 | frpc | `651de3428bdc7f37b4bad76ed3236b221939a989c433cd7daee79d2817519f8b` |
| 0.71.1 | arm64 | frps | `45a45650cf6ad2568a90f646b1ad79ac483510c1d845ecc55c532ad271ff5366` |

Only amd64 binaries were executed; arm64 archives/binaries were hashed and ELF
architecture checked. This is not an arm64 runtime qualification.

## Relationship to the reported 8–10 minute stalls

Supporting: the project pins the affected source/binaries; WSS still reaches the
same dispatcher; generated mux/default-heartbeat combination matches a condition
from the upstream report; working listeners/healthy backends do not exclude it.

Against a definitive diagnosis: no synchronized live control-error/relogin
traces, no live process hash/config proof, no demonstrated initial write error,
and no causal 8–10 minute timer in this defect. Recovery without a manual restart
can also arise from network interruption, a peer close or other timeout. XHTTP,
mobile ISP/NAT, VPS scheduling/packet loss, Nginx and application behavior remain
possible. Faster initial traffic or a new XHTTP inbound does not distinguish them.
The isolated defect and the cause of the live symptom are separate conclusions.

## Limited upgrade decision and gates

Decision: upgrade to upstream 0.71.1 is recommended to remove the reproduced,
reachable defect, after the following qualification gates; no immediate live upgrade;
causality for these stalls needs synchronized evidence. Do not deploy a local
FRP repair patch or silently change heartbeat/tcpMux.

1. Verify the exact official archives and binary hashes on both architectures;
   retain old artifacts, manifests and signed runtime records independently.
   Hashes obtained over GitHub HTTPS are integrity/provenance evidence, not an
   invented detached vendor signature or a reproducible-build claim.
2. Rebuild reviewed Smite images with official 0.71.1 only, run signed transport,
   WSS, owner/child, replay and negative security suites; publish signed images
   with immutable digests through the existing release pipeline.
3. Qualify the existing U-OPTI migration/rollback path against an active shared
   owner. Today the RC7 version/image/runtime gates deliberately pin 0.71.0;
   replacing binaries or editing fingerprints in place is NOT an upgrade path.
   Preserve signed pairing/replay/grants, owner/child IDs and token. Never use
   signature DNS recovery to authorize an engine upgrade.
4. Agree a maintenance window and independent backup/recovery console; owner
   replacement has a shared interruption boundary. Upgrade only with separate
   approval after that exact signed-image transaction is qualified.
5. On failed admission stop before mutation. On interrupted upgrade retain the
   journal and determine which reviewed runtime is active. Restore the exact
   previous images/binaries and matching receipts through the existing rollback
   transaction; never delete ledgers or retry ambiguous publications.

This PR is an investigation/test PR, not a production version bump. A production
upgrade PR is gated on the signed-image/active-owner migration qualification.

## Concurrent IR / Grandoptical observation (operator-run, read-only)

On BOTH hosts, from the same reviewed checkout, start this at approximately the
same UTC time before reproducing the stall. It reads only new bytes from the
existing Smite FRP log files for 12 minutes and prints 30-second UTC buckets:

```sh
# BOTH — same command on IR and Grandoptical; no install or log-level change
 docker exec -i smite-node python3 -B - < tests/lab/frp-control-stall/observe.py
```

Label the two captured outputs IR and Grandoptical externally. Record the UTC
second when the viewing pause starts/ends and whether direct Grandoptical shows
the same pause on the same device/ISP. The probe prints only allowlisted event
counts, process counts, load and cumulative network errors/drops. It never
prints raw lines, filenames, process argv, IP addresses, tokens, keys, configs
or client data. Run `date -u; vmstat 1 5` on BOTH hosts near a pause for host-side
CPU steal, run queue, memory and I/O pressure; these are numeric diagnostics.

Interpretation: one steady FRPS count does not prove healthy controls. A rise
in work-connection failures plus a subsequent relogin is relevant, but not
unique to this bug. Cross-host network errors/steal and direct-connection stalls
support network/VPS alternatives. ReqWorkConn and the original swallowed write
may not be logged at the current log level; a zero count does NOT rule the bug
out. Rotation/truncation/read-error counters expose incomplete log windows.
Do not enable debug logging, restart FRPC, or change heartbeat settings during
this initial observation. No live diagnostic was executed by this PR.
