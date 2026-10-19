# U-OPTI + Smite: ONE clean two-node rebuild (release gate, DRAFT)

**Decision (2026-10-19):** Do not rebuild the current IR/KH test pair
while security, independent-engine lifecycle, and onboarding are unfinished.
The existing U-OPTI 0.16.7 setup is a working baseline with FRP and Backhaul.
Keep it unchanged until there is a reviewed, installable release candidate.
No background rebuild, forced migration or silent Stable/main merge.

## Freeze gate — all of these are needed BEFORE the one rebuild

| Gate | Acceptance | Current evidence |
| --- | --- | --- |
| Smite Node strict Agent HMAC, replay persistence, signed Panel/Node pairing | Fail-closed unsigned/stale/replayed requests; no legacy silent fallback | PR CI proofs exist; physical IR/KH untested |
| Strict-mode Docker health | Loopback-only `/healthz` works after Node initialization, while `/api/agent/*` still requires HMAC | Smite experimental branch fixed; cross-repo CI still needs final green |
| Simplicity and account security | Reviewed simple operator UI, optional TOTP enrollment/recovery, server-side logout with all-device JWT revocation | Smite CI passed on reviewed branch; live login/recovery drill and release approval still pending |
| Clean Smite Core | Install Panel IR and Node KH with no FRP/Backhaul initially; no default tunnel ports | Clean-RC in PR, not deployed |
| Independent engine installer | Backhaul **and** FRP can each install independently; no automatic dependency, no static Xray inbound at engine install | Backhaul PR sandbox validated; official FRP v0.71.0 dual-binary *offline candidate* added and awaiting CI; both production buttons remain HOLD |
| Rollback and coexistence | Preserve identity, replay DB, data volume and active tunnels; never overwrite live FRP or other engines; restore cleanly if Node recreation fails | Docker Compose isolated rehearsals only, no host recovery approval |
| Image/artifact provenance | Exact image digest and official per-architecture engine release SHA256; no unpinned `latest` | Experimental pinning exists, final release lock pending |
| Operational safety | Console access and tested provider Snapshot restore for **both** disposable hosts | Human verification pending |
| Full PR acceptance | All relevant U-OPTI/Smite CI green on mutually pinned final SHAs; manual review and explicit operator approval | NOT YET |

**If any gate is missing, do not Rebuild.** A green CI test does not
unlock the real-host installer or confirm TLS/443 transport.

## ONE planned rebuild — only after all freeze gates are met

1. First verify recoverable snapshots and emergency console for both
   disposable hosts. The current working FRP/Backhaul setup remains the
   reference until this explicit handover.
2. Rebuild **IR test host** once; install the frozen U-OPTI candidate,
   independent Smite Core (Panel + Iran-role Node) and strict pairing.
   Confirm local health, signed checks, persistence after reboot and no
   implicit engine enrollment.
3. Rebuild **KH test host** once; install frozen Core and independently
   pair the foreign Node, plus 3x-UI. Verify secure one-port HTTPS 443
   gateway and no unapproved public port exposure.
4. Install **Backhaul only**, independently once per IR and KH; it must
   report `ready` on both Nodes before a Panel-defined tunnel can be
   created. Set port and path in the Panel **after** 3x-UI is ready;
   never during software installation. Test traffic and fault recovery.
5. Install **FRP separately**, after Backhaul proves functional.
   Confirm installing or stopping either engine does not modify the
   other or require a repeated Smite Core installation.
6. Exercise real service restarts, disconnection/reconnection, signed
   identity/replay preservation, rollback, Xray inbound changes, and
   dynamic Panel tunnel mapping. Compare against current known-working
   FRP/Backhaul baseline. Record and fix failures on experimental
   branches; do **not** force another rebuild to mask an installer bug.

## Operator UX (target)

A simple menu with `Install / Verify / Repair / Remove` per independent
engine, plus two understandable statuses: `Ready` and `Needs attention`.
Security, downloads, checksums, retries and journaled rollback stay
behind the scenes. "Ready" for an engine never implies a working tunnel.

## Change policy

- No production IR/KH commands, package upgrades, exposed ports, tunnel
  reconfiguration, release publication, Stable/main changes, or PR merges
  without explicit user approval.
- Draft PRs: `aghajani82/u-opti#38` and `aghajani82/Smite#15`.
- A separate smoke test on disposable infrastructure may be approved
  later, but **no automatic rebuild of the current working pair now**.
- Report actual test failures rather than concealing them; preserve
  snapshots and working settings and keep the install button HOLD until
  real-host transaction and rollback admission is reviewed.
