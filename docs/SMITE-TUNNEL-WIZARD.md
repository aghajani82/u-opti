# Tunnel Setup Wizard — beginner-facing preview (Draft PR #18)

## Where it appears

`U-OPTI → Docker Management → Smite Management → 5) Tunnel Setup Wizard`

This is an **additive preview** on `feature/smite-standard-backhaul`.
It does not replace the existing 10-step Private Network Wizard, the current
Standard FRP Setup Wizard, or the Backhaul candidate staging menu.

## Protocol support and truthful capabilities

| Protocol | IR and KH role screens | Status checks | Installs live tunnel? |
| --- | --- | --- | --- |
| Independent Backhaul 0.7.2 | Yes | Read-only host readiness + explicit private offline candidate generation | **No** — setup checklist and secure candidate only |
| Standard FRP | Yes, delegated to existing `smite-frp-wizard.sh` | Existing FRP diagnostics | Existing FRP wizard handles its opt-in setup steps |
| Rathole | Yes | Validates dedicated ports; explains TCP and optional WSS feasibility | **No** — TCP planning only until pinned binary, auth, bind, TLS/Noise, backup and rollback are reviewed |

Never present a staged candidate, a HTTP 400 from Xray, a HTTP 401 on
Backhaul `/channel`, or an `ESTABLISHED` local Nginx connection as proof
of a fully authenticated end-to-end VLESS tunnel.

## Role identification

When available, the wizard reads the user's existing Smite standard-mode
role, `panel-iran` → `ir` and `foreign` → `kh`. On a new host with no
Smite role it asks the operator to choose IR or KH. This fallback **does not
write any role state** and never installs based on a guess.

## Backhaul currently verified in an actual two-server manual pilot

The operator previously verified a **manual**, separately controlled
IR/KH build:

- IR: Nginx HTTPS on :443 → internal :8443 → WebSocket `/channel` and
  `/tunnel/` → independent Backhaul server on `127.0.0.1:3080`.
- KH: independent Backhaul client → local Nginx :13080 → verified HTTPS
  on IR. KH Nginx public `/13080/...` forwarding is explicitly denied.
- IR: private Sidecar data listener `127.0.0.1:56053` →
  KH Xray `127.0.0.1:56053`; HTTPS path `/56053/www/`.
- Both named Sidecar containers use the pinned Smite Node image with Backhaul
  v0.7.2, private tokens and restart policy `unless-stopped`.
- Both machines were rebooted separately. The operator verified a working
  real XHTTP client after each reboot. These are **user-observed manual
  pilot results**, not automatically reproduced installer tests.

This setup was successful with the user's particular existing Smite,
Nginx, FRP and Xray topology. It **cannot be safely copied to a new
host** without auditing its SNI maps, exposed proxy paths, ownership,
port bindings, existing services, certificates and rollback.

## Rathole is a different transport

Rathole forwards TCP/UDP services and supports optional WebSocket transport
in compatible builds (official Rathole v0.5.0 introduced WebSocket). It does
**not** use Backhaul's `/channel` and `/tunnel/` endpoints. The first Rathole
wizard stage validates distinct control/data ports and prints a **non-executable
TCP plan**. The WSS/443 checklist is review-only: sharing IR 443 requires
a reviewed Nginx route, verified WS handshake/path support for the pinned
binary, and explicit protection of the existing site, FRP and Backhaul.
Neither checklist is an installer.

Before Rathole installation can be offered, the project needs:
a pinned verifiable release/artifact, explicit protocol choice, authenticated
service token without terminal/log exposure, TLS/Noise review, inbound port
and firewall review, hostname and certificate controls where applicable,
systemd or container lifecycle, fail-closed ownership checking, complete
backups and a proved rollback on disposable hosts.

## Phase 2: Local readiness checks (implemented in Draft PR)

A read-only local auditor is now available as
`modules/smite-backhaul-sidecar-readiness.py`. The beginner Backhaul
submenu exposes two role-aware commands:

- **Audit existing installation**: inspects the pinned Sidecar image,
  host networking and auto-start policy, loopback port ownership, Nginx
  syntax, private file modes, fixed Sidecar routes, TLS verify directive
  and KH public-forwarding guard. Prints only safe status messages,
  not tokens, config contents, IPs, PIDs or container mount paths.
- **Preflight a fresh server**: refuses if a named Sidecar, pre-existing
  Sidecar files, or conflicting reserved listeners are present; verifies
  the expected FRP/Smite/Nginx/Xray baseline for the selected role.

This is **not** a transactional installer and does not claim that
certificates, external reachability, authenticated WSS, end-to-end
XHTTP/VLESS, safe Nginx integration, backup provenance or tested
rollback are complete. The chosen role is user-supplied if Smite
state cannot identify it. Unexpected owners or missing inspection
permissions produce HOLD, not success.

Synthetic CI tests cover port collisions, incorrect ownership,
unexpected public binds, non-verifying TLS bridge, swapped Nginx
location order, partial installation, stale image/restart policy
and absent inspection evidence. These are hermetic tests and do not
connect to real IR/KH machines.

## Phase 3: Nginx integration plan (offline, implemented)

The beginner Backhaul wizard now offers **Prepare Nginx merge/rollback file
plan**, using `modules/smite-backhaul-sidecar-nginx-plan.py`.

- For IR, it refuses unknown HTTPS backend topology and only prepares
  `/channel`, `/tunnel/`, and `/56053/www/` include candidates
  within the existing single HTTPS backend, preserving FRP and the root
  Smite upstream.
- For KH, it checks the existing numeric port-forwarding expression and
  proposes an explicit /0*13080 block before that expression, alongside
  a separate loopback Nginx bridge verifying the IR certificate.
- Exact original and prepared vhost **bytes** are staged privately with
  SHA256 hashes and a manifest listing intended create/replace targets.
  The folder mode is 0700; all staged files are 0600. Existing Nginx
  vhosts are **never changed** by this planner.
- Existing Backhaul locations, duplicate anchors, missing or unknown
  server blocks, mismatched domain names and incompatible vhosts
  result in **REFUSED**, not a guessed rewrite.
- Both proposal layouts have Python fixture tests plus a separate
  isolated real-Nginx-in-Docker syntax validation job. Those tests do
  not operate on the user's live servers or prove production TLS,
  wildcard routing, backup restorability or Xray connectivity.

**Important:** Because the plan contains a copy of the original Nginx
vhost, it may hold private information. Never upload or paste its
`original.conf`, `patched.conf` or other staged files publicly.
Unlike a transactional installer, this planner is **not executable
deployment authorization**: there is still no live journal/backup
activation, lifecycle reconciliation, cross-host trust check or proven
rollback action attached to it. A server with the successful manual
Sidecar already present is expected to fail the "fresh install" plan
rather than overwrite that installation.

## Phase 4: Crash-safe transaction coordinator (synthetic laboratory)

`modules/smite-backhaul-sidecar-transaction-lab.py` now coordinates
the existing file recovery journal with a **fake, JSON-only service
adapter**. This is deliberately **NOT an installer** and is NOT
packaged in the production U-OPTI install/update manifest.

The simulated sequence is:

1. Acquire a private sandbox coordination lock; reject any already
   installed/partially applied Sidecar or unknown file state.
2. Write a durable intent record BEFORE invoking the separate
   write-ahead file journal; never store a token or configuration
   body in either journal.
3. Simulate a Nginx validation checkpoint and the independent
   Sidecar launch without running Docker or opening network sockets.
4. Simulate a Nginx reload and health checkpoint while preserving
   fake Smite, FRP and Xray states.
5. On an ordinary failure, reverse only verified resources automatically.
   If the process is interrupted, a separate recovery invocation
   checks **all** owned files and mock services before touching anything.
6. Restore the fake service state, recover the existing file journal,
   and delete the coordination intent **LAST**, so an interrupted
   recovery can resume without guessing.

New hermetic tests inject failures and simulated power losses at every
checkpoint and **every file write boundary**, as well as crashes
before the first original-file backup, during both recovery phases,
duplicate deploy attempts, symlinks, foreign file drift and foreign
service-state drift. Divergent states refuse rollback.

**Outstanding safety blockers before a live implementation:** the
sandbox file allowlist must be reconciled with the newer role-specific
Nginx plan, including the KH public /13080 forwarding guard. The
production engine must verify the exact running container ownership,
pin a Docker image and restart policy, preserve file ownership/modes,
record restorable original backups (not only hashes), test Nginx
against the **actual complete** configuration, coordinate container
start/reload failure rollback, and handle operator recovery after a
reboot or loss of SSH. End-to-end verified WSS/VLESS remains separate
from HTTP GET probes and mock health state.

**No live IR/KH changes are made by this transaction laboratory.**

## Phase 5: Unified IR/KH ownership and Nginx rollback lab

The offline proposal and rollback logic now have a **common,
fail-closed resource definition** in
`modules/smite-backhaul-sidecar-reconcile.py`. The reconciler reads
two independently private candidate folders, recomputes the output of
both the pinned Sidecar candidate generator and the Nginx compiler,
checks the hashes and exact target paths in `plan.json`, and blocks
an incorrect token, domain, Nginx file, include, symlink, weak file
permissions, unknown target or duplicate file. It does **not** print
or put authentication material into a recovery journal.

The reconciled synthetic transaction covers:

| Role | Created resources | Existing Nginx file edited and backed up |
| --- | --- | --- |
| IR | Sidecar TOML, Compose candidate, Backhaul WS and XHTTP includes | Smite HTTPS backend on 127.0.0.1:8443 |
| KH | Sidecar TOML, Compose candidate, TLS-validating loopback Bridge | KH HTTPS vhost containing the guarded numeric port-forwarding regex |

**KH guard integrity is a prerequisite**: the edited KH vhost must deny
`/13080/` and its leading-zero variants before the existing numeric
forwarding regex. Both its exact original bytes and the patched version
are included in the mock file journal, making its rollback scope
symmetric with IR's backend edit.

`modules/smite-backhaul-sidecar-unified-lab.py` is a marker-guarded,
private `/tmp`-only simulator. It writes a durable intent before
file changes, saves the original vhost, applies only recognized
synthetic paths, exercises mock Sidecar start/Nginx reload, checks all
file and mock-service states before recovery, and deletes its journal
last. A simulated interruption during install, restoration, or
journal finalization can be recovered by a separate invocation.
Unknown Nginx drift, journal tampering, symlinks, absent backups and
unexpected mock service mutations cause a HOLD without guessing.

Hermetic CI tests cover IR and KH, each file write checkpoint,
all service checkpoints, double installs, missing files, the KH
public-forwarding guard, restorable original vhost bytes, and
interrupted rollback. These tests **do not** change any real machine
or perform a live container start, Nginx reload, TLS handshake or
VLESS connection.

**Still not a production installer:** the existing historical
simulation modules retain an older sandbox allowlist and must not
be treated as equivalent to this newer unified scope. Before live
deployment we need an audited transition to a production journal,
host file ownership/mode preservation, durable backup of actual
Nginx/certificate dependencies, exact container provenance and
lifecycle, full Nginx configuration validation on target machines,
a public-forwarding bypass review, end-to-end authenticated network
checks, and failure/reboot handling on two disposable servers.
The PR remains draft; do **not** merge or execute the simulator
against IR/KH.

## Next development milestones

1. Convert the manual Backhaul pilot into a **transactional**, versioned,
   role-aware installer with checked immutable image/binary, listener
   ownership, existing Nginx server context, host-both backup provenance
   and tested rollback (not just a hash record). The wizard must visibly
   warn and stop when preconditions do not hold.
2. Add a non-secret pairing method so beginners do not paste shared
   Backhaul or FRP tokens in a terminal, shell history or chat.
3. Expand the current FRP wizard with beginner progress, a role-specific
   preflight and reliable real-client verification, retaining existing
   panel management and Private Network flow.
4. Implement the Rathole transport as an isolated, independently reviewed
   module with real tests. Do not reuse HTTP location code.
5. Simulate first install, repeated install, failed upgrade, failed Nginx
   test, power/reboot, token mismatch, public forwarding bypass and
   rollback in independent Docker fixtures **before** allowing live
   writes through the unified wizard.

## Security boundary

The new unified wizard itself has **no live deployment, stop,
restart, reload, active Nginx/config write, firewall mutation,
credential print or public port open** operation. Its only
new write action is an explicitly confirmed, private, uninstalled
candidate bundle under a fresh temporary directory; this contains
credentials and must never be uploaded or posted. Only the existing FRP wizard is delegated to
for its previously implemented actions. All commands behind Backhaul
"Status" are bounded read-only local checks. Operators must still
explicitly consent to any actual installation and have access to
Hetzner console and restorable off-server backups.

Do not merge this draft PR into `main` or run experimental installer
code on IR/KH merely because a CI job is green.
