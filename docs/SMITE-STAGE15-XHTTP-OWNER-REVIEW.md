# Stage15 existing-owner XHTTP candidate — source review, not rollout approval

Counterpart: Smite `8edbd4032ae657fe2bb38cd9b3290de5f1e07a54` (PR #40).
Do not merge either PR until actual VLESS/XHTTP client traffic, denial cases,
reboot persistence and rollback pass on the disposable hosts.

## Implemented

- Stage15 bridge has a separate root-owned journal and before-image. The WSS
  journal is not rewritten; its original backend hash and alternate backend
  remain authoritative. Only an exact include insertion in 8443 is admitted.
- Broker verifies a committed Stage15 bridge. Missing, prepared, corrupted or
  rolled-back state never falls back to an RC5 verifier.
- Direct owner route binds owner/subject/binding ID to the existing tunnel ID,
  verifies the single owner signed proof, existing proxy port and KH inventory,
  and rejects conflicting rows/leases. It does not create a child or apply FRP.
- GUI selects a signed inbound port/path and exposes the action for the owner.
  Configure the chosen inbound port/path in Sanaei's GUI first. Existing owner
  port cannot be silently changed by a route publication request.
- Canonical custom paths use ASCII segments, length <=128 and reserved panel
  namespace denial. Root checks all effective literal Nginx locations, upstream
  reuse and prefix collisions. Unsupported regex/named/quoted layouts HOLD for
  review, rather than assuming they do not collide.
- Missing-grant requests can stage one bounded HMAC-authenticated proposal.
  They cannot mint grants or consume a route nonce. Root reviews the exact
  facts and hashes on an independently authenticated console and confirms the
  request digest; a durable audit precedes grant creation. The 30-second
  signature expiry is rechecked after confirmation. No port/path transcription.
- Route journal supports explicit rollback/recovery, rejects external content
  drift, and does not restore the replay database or restart FRPS.

## Still a rollout blocker — do not use the old image upgrader

`smite-stage15-upgrade.py` only admits the pre-engine, pre-WSS old image pair.
It requires no tunnels and absence of WSS overlays. It MUST NOT be used on the
current active owner. `smite-stage15-wss.py` also pins the existing reviewed
image IDs and runtime signature. A new Panel image must be admitted by a
separately reviewed runtime migration preserving the WSS journal, Signed state,
Replay and running IR Node/FRPS. Do not change the pins by hand.

Existing `/usr/local/libexec` worker/planner and root broker config contain
pinned old digests. Updating the source checkout does not migrate these files.
A journaled worker/config migration and broker restart must be reviewed before
rollout. Do not overwrite pins/config manually or rerun fresh provisioning.

New image publication and that active-runtime migration are not implemented by
this candidate. No claim of an installable, complete E2E solution is made.

## Conditional field-trial sequence

Do not start Apply until the rollout blockers above are closed and exact image
and installer SHA/provenance are verified. No Grandoptical actions.

1. **BOTH — Snapshot:** provider snapshots and console access; capture the
   current signed identities, Replay continuity, owner ID/PID, ports and WSS
   journal digests without printing credentials.
2. **IR — Preflight:** on the reviewed staged runtime, run
   `python3 -B /usr/local/lib/u-opti/modules/smite-stage15-xhttp-bridge.py plan`.
   Require one existing owner, loopback 7000/45121, empty managed routes, exact
   committed WSS journal, 8443 Panel, unchanged 8444 and KH SNI/IP allowlist.
3. **IR — Apply:** run the same bridge tool with `apply`; confirm the snapshot
   challenge. In Smite select the existing owner and its KH inbound via XHTTP.
   Review the signed pending request via Stage15 menu G on authenticated IR
   root console, then submit a fresh route request from the Panel. Do not
   delete/reapply the owner, create another 45121 child, or run edge Apply.
4. **BOTH — Verify:** bridge `verify`, WSS verify, unchanged owner PID/ports,
   Signed/Replay checks, effective exact/prefix Nginx route, actual VLESS/XHTTP
   client traffic, rejected unauthorized paths/SNI/IP, then reboot persistence.
   Route registration alone is not client traffic proof.
5. **IR — Rollback:** revoke the exact root grant; inspect and roll back the
   route with the pinned local helper's `--rollback --confirm-local-root`
   using the approved grant's port/path. This intentionally requires local
   root. Then bridge `rollback` (or `recover` after interruption). Published
   routes/unreconciled transactions block bridge rollback. Keep WSS and owner
   running. Never restore an older live Replay database.

## Evidence scope

Local tests and CI use isolated fixtures. The cross-repository workflow pins
Smite to the exact SHA above and checks canonical signatures, replay rejection,
exact grant mismatch, identical worker/planner bytes and rollback. They do not
prove that current IR/KH images contain this code or that the client connects.
