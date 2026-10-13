# Tunnel Setup Wizard — beginner-facing preview (Draft PR #18)

## Where it appears

`U-OPTI → Docker Management → Smite Management → 5) Tunnel Setup Wizard`

This is an **additive preview** on `feature/smite-standard-backhaul`.
It does not replace the existing 10-step Private Network Wizard, the current
Standard FRP Setup Wizard, or the Backhaul candidate staging menu.

## Protocol support and truthful capabilities

| Protocol | IR and KH role screens | Status checks | Installs live tunnel? |
| --- | --- | --- | --- |
| Independent Backhaul 0.7.2 | Yes | Read-only diagnostics; explicit private offline candidate generation | **No** — setup checklist and secure candidate only |
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

Rathole is a reverse TCP/UDP tunnel, not an HTTP WebSocket tunnel using
Backhaul's `/channel` and `/tunnel/` endpoints. The first Rathole
wizard stage validates nonprivileged distinct control/data ports, rejects
known reserved pilot ports, and prints a **non-executable plan**. The plan
is not sufficient to operate or secure Rathole.

Before Rathole installation can be offered, the project needs:
a pinned verifiable release/artifact, explicit protocol choice, authenticated
service token without terminal/log exposure, TLS/Noise review, inbound port
and firewall review, hostname and certificate controls where applicable,
systemd or container lifecycle, fail-closed ownership checking, complete
backups and a proved rollback on disposable hosts.

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
