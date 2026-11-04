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


## Independent-backup alternative (signature policy operations only)

When provider snapshots are unavailable, `signature-recover` and
`signature-rollback` accept `--recovery-backup` plus `--backup-sha256` instead of
`--snapshot-confirm`. These options cannot authorize apply, runtime rollback,
runtime recover, plan, verify or signature-check. Mixing the two proof modes is
rejected. Never assert that a provider snapshot exists when it does not.

The backup input is **the original committed WSS record.json restored from the
independent off-server backup**, not an archive, a manifest, a fresh copy of the
live journal or a record already changed to the new policy. The file must be
root-owned, mode 0600, regular, single-link, at an absolute path with no symlink
components. Keep the backup private: its receipts may contain sensitive paths.
Its SHA-256 must be retained/retrieved independently OFF HOST, not computed from
the candidate on IR and then used as its own proof. If the historical original
journal is absent from the independent backup, this path must HOLD.

The helper checks the externally anchored hash, rejects duplicate JSON keys,
and compares the complete original document against the current committed
journal, allowing only the removal of the reviewed signature_policy field.
Roles, ownership, protected receipts and all original fingerprints must match.
It restores those bytes to a disposable private file, fsyncs and reads them
back, checks mode/owner/content and parses them again. It never restores over
production files. This is a **journal-only restore drill**, sufficient for this
policy-only mutation; it is not a test or authorization of a full host restore.

Cryptographic integrity does not prove where a copy is physically stored. The
operator must actually retrieve the copy and its previously retained checksum
from independent storage. The explicit OFF-HOST-RESTORE-VERIFIED confirmation
attests this human-verified fact. The helper does not contact the backup provider
and does not claim that a flag alone verifies independent custody.

Use the provider's recovery console and log into the installed IR system as
root. The helper requires a foreground Linux virtual/serial console
(`/dev/ttyN`, `/dev/ttySN`, `/dev/hvcN`, `/dev/ttyAMAN`), with stdin and stdout on
the same device. SSH, PTYs (`/dev/pts/*`), redirected input/output and background
sessions fail closed. Do not use SSH, tmux, screen, `script`, a pipe or a here-doc
to simulate console access. Consoles exposing only a PTY are unsupported by
this bounded alternative. Merely having a console URL is insufficient.

After the independent backup copy has been retrieved, its historical digest
verified and the reviewed project update installed, run from the IR console:

```sh
python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-check --role ir
python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-recover --role ir --recovery-backup /root/ir-wss-original.json --backup-sha256 <OFF_HOST_SHA256>
python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-check --role ir
```

Replace `<OFF_HOST_SHA256>` with the independently retained 64-character digest
before running; the angle-bracket placeholder is not a shell argument.
The helper checks backup and runtime before asking for these two exact inputs:

1. `OFF-HOST-RESTORE-VERIFIED ` followed by that digest.
2. `SIGNATURE-RECOVER-RC7-WSS-IR`.

Policy-only rollback uses the SAME original independent backup and checksum:

```sh
python3 /usr/local/lib/u-opti/modules/smite-rc7-wss-runtime.py signature-rollback --role ir --recovery-backup /root/ir-wss-original.json --backup-sha256 <OFF_HOST_SHA256>
```

The second challenge becomes `SIGNATURE-ROLLBACK-RC7-WSS-IR`. A cancelled prompt,
invalid/incomplete backup, failed restore drill, interrupted journal, failed
console check or any runtime/protected-file drift stops before commit. The
existing atomic write and interrupted-record handling remain in force. Repeat
recovery and rollback retain the original signatures. Only the journal policy
is changed; containers, FRPS, Broker, replay ledgers and grants are untouched.

This alternative does NOT reconcile or retry `optical` (port `38276`). Keep that
outcome unknown until its independent evidence is reconciled. The active tunnel
`FRP-IR-Grandoptical-20182` must remain unchanged. No live deployment is implied
by these instructions; it still requires separate authorization.
