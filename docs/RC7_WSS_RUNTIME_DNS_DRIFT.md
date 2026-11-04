# RC7 WSS runtime: bounded empty-DNS equivalence

Base: `3ee216dd7dc2337f3316577a0c14df0af2f94046` (main, PR #96).

## Cause and limits of evidence

The old runtime digest hashes all HostConfig fields. Docker can serialize an
empty DNS slice as null or []. Moby's `Container.readHostConfig()` calls
`InitDNSHostConfig()`, which converts precisely Dns, DnsOptions and DnsSearch
from nil to empty slices when loading containers from disk. Reference:
https://github.com/moby/moby/blob/v28.3.1/container/container.go
(`readHostConfig`, `InitDNSHostConfig`). A daemon restart / host reboot can
therefore change the digest without changing DNS configuration. Current memory
and disk HostConfig equality does not compare either with the historical digest.

This is a proven source-level failure mechanism, **not yet confirmation of the
cause on IR**. No live IR evidence was collected or modified. The local proof
must match IR's original digest exactly; otherwise recovery HOLDS. RestartPolicy
is not exempted, even in combination with empty-DNS changes.

All original fields remain hashed. Only present empty DNS fields may alternate
between null and []; missing keys, nonempty DNS values, new HostConfig keys,
network mode, capabilities, mounts, images, environment, command and restart
policy remain significant. There is no generic null/empty normalization.

## Existing and new records

Legacy records remain strict by default. `signature-check` performs the existing
health/image/signed-mode/Compose ownership/protected-file checks, then tests at
most eight DNS-only alternatives against the original digest for every service.
It performs no signed probes, nonce consumption, route publication or writes.

`signature-recover` repeats those proofs under the engine lock and atomically
adds `signature_policy: docker-dns-empty-v1` to each baseline. It never replaces
the original signature. Each subsequent consumer repeats the bounded comparison.
No startup, verify or broker path silently migrates old records. New activation
records use the canonical empty-list digest and the same explicit policy.

`signature-rollback` atomically removes only that policy. It does NOT call the
older runtime rollback/recover functions (which recreate containers). After
policy rollback, legacy DNS drift can intentionally HOLD again. Re-enable only
through the same proof-gated signature recovery. An interrupted `record.next`
blocks further signature recovery; preserve both files for comparison. Never
promote a temporary journal or delete it blindly. The committed `record.json`
is replaced atomically, so a failed pre-rename write leaves the prior document.

## IR procedure — only after tests, reviewed installation and separate approval

Use the project updater to install the reviewed merged revision first. No
standalone installer, direct disk HostConfig edit or container recreation.

Read-only proof (does not consume a replay nonce):

```sh
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-check --role ir
```

Proceed only on `RC7_WSS_SIGNATURE_RECOVERY=PROVEN_READ_ONLY`. Any HOLD requires
investigation; do not edit the signature or relax checks. After the separately
approved provider snapshot / console prerequisites:

```sh
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-recover --role ir --snapshot-confirm SNAPSHOTS-CONSOLES-VERIFIED
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-check --role ir
```

Interactive challenge: `SIGNATURE-RECOVER-RC7-WSS-IR`.
Policy-only rollback, if needed:

```sh
sudo python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-rollback --role ir --snapshot-confirm SNAPSHOTS-CONSOLES-VERIFIED
```

Interactive challenge: `SIGNATURE-ROLLBACK-RC7-WSS-IR`.
Do not run the older `rollback` or `recover` actions for this problem.

## The optical publication is a separate unresolved incident

The Panel's `BROKER_ROUTE_RESULT_UNCONFIRMED` is a generic non-success response;
it does not prove absence or presence of an applied route. Broker `process()`
checks `_verify_bridge()` before grant lookup and before
`authenticate_and_consume()`. A WSS drift rejection at that exact boundary
cannot consume the broker nonce. An apply failure after consumption is different
and deliberately returns `ROUTE_APPLY_HOLD_RECONCILE_NO_RETRY`.

For the exact optical child/lease/port/request time, separately correlate the
existing Broker journal, root grant, nonce ledger (read-only SQLite connection),
`/etc/nginx/smite-xhttp-routes/<port>.conf` and `.<port>.transaction.json`, and
Panel child/lease records. Do not print secrets or raw signed wire. A route file
alone is not evidence that Nginx loaded it; an absent file is not evidence that
a nonce was unused. Without matching evidence leave the outcome UNKNOWN.
Do not click Register again, resend wire, renew/delete a grant, clear a ledger,
or issue a new nonce as part of signature recovery. No automatic reconciliation
or resubmission was added. Existing FRP-IR-Grandoptical-20182 remains untouched.

## Validation scope

Unit tests exhaust all 64 before/after DNS combinations, strict legacy behavior,
security/unknown-field negatives, no nonce/route side effects, atomic recovery,
repeat recovery, policy rollback and interrupted-write HOLD. Existing runtime,
preflight, enrollment, bridge and broker regressions also run.

The dedicated CI job uses a disposable container with no network or host mounts,
checks its ID and signature after container restart and Docker daemon restart.
It must never run on a live server. This is NOT a full VM reboot test; no full
host reboot was performed in this environment, which has no Docker executable.
