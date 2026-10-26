# U-OPTI — staged Smite Node pairing preview (2026-10-18)

**DRAFT. Do NOT install on production, merge to main, or call it complete Node authentication.**

This changes no live IR/KH server. It is stacked on the Standard Node
127.0.0.1:8888 protection patch (U-OPTI #28). The new Smite pairing APIs
are still disabled by default (Smite drafts #2 → #3 → #4).

## Goal and user flow

Maintain ONLY public 80/443, keep Smite Node on local
`127.0.0.1:8888`, preserve U-OPTI/Smite FRP and Backhaul overlays.

1. Admin signs into the **IR** Smite panel and verifies the existing Node ID,
   role and hostname *out of band*, without trusting legacy anonymous register.
2. Panel issues an approved one-time 10-minute code using an authenticated
   admin endpoint. The **UI for this is not implemented yet**.
3. User on the target Node (IR or KH) enters the approved UUID and hidden
   pairing code into the new U-OPTI workflow. It submits credentials in a
   JSON body **only** to certificate-verified `https://panel-domain:443`.
4. The Node's secret is staged in a root-owned 0700 directory and 0600 file;
   no secret is printed or sent to the regular U-OPTI logs.
5. **Later coordinated rollout**: update the Panel overlay, Node
   image+overlay, Nginx trusted ingress proof/ratelimiting, lifecycle
   helpers, credential mounts, signed heartbeats/FRP updates and
   authenticated tunnel operations. Never enable strict mode early.
6. Only after two-sided proof, perform disposal-test-server IR/KH checks,
   then consider a separate public release.

## What this draft adds

- `modules/smite-node-pairing.py`: standalone **stdlib-only** HTTPS
  pairing client. Refuses HTTP, arbitrary ports and redirects, redirects and
  environment proxies; validates the system CA and hostname via
  `ssl.create_default_context()`. The code is obtained through
  `getpass.getpass` in interactive mode and never passed in CLI arguments.
  The secret is stored with exclusive creation (no overwrites) in
  `/etc/u-opti/smite/identities/node-identity.json`.
- `modules/smite-node-pairing-wizard.sh`: preview menu, **read-only status**,
  opt-in private 0700 directory preparation, and simple explanation of
  the future workflow. There is no live Pair button.
- `u-opti --smite-pairing`: explicit standalone preview entry point.
  Existing Docker/Smite/FRP/Backhaul menus and guided IR/KH installer
  remain byte-for-byte unchanged; the wizard is not yet shown inside
  the primary menu. This is intentional to avoid altering live menus.
- Installer and updater include both files. New offline GitHub CI tests
  validate URL policy, metadata, permissions, network-off-by-default,
  TLS handler, redirects, secrets, packaging and preservation of older
  wizard files.

## Explicit activation HOLD

The direct Python flag `--redeem-preview` is inaccessible from the menu
and is disabled unless an operator **explicitly** sets
`UOPTI_SMITE_PAIRING_PREVIEW=1`, runs as root in an interactive terminal
and types `PAIR-CREDENTIAL-ONLY`. Even then it stages a secret **only**:
it does **not** mount it to the Docker Node, change legacy registration,
start/stop any container, open any firewall, update Nginx or secure any API.

Until these milestones complete, we recommend **not setting that flag**.
In particular, a one-use code may be consumed before the new secret is
mounted, so the operator would require a separate recovery flow to retry.
The server's one-time enrollment endpoint also requires a correctly
restricted, authenticated TLS/443 Nginx ingress and opt-in config; without
this it rejects the request.

## Rollout checklist (NOT YET complete)

- [x] TLS-enforced, secret-free-on-stdout Node pairing client (offline tests)
- [x] Isolated read-only prep wizard; no existing wizard changes
- [ ] Admin-facing Pairing UI in Smite and secure pre-existing Node identity
- [ ] Rate limits, Nginx token injection, and trust boundary for HTTPS/443
- [ ] Panel/Node dual-side HMAC authentication for all status and control
- [ ] Private Node credential mount/persistence across Docker upgrades
- [ ] Reconcile U-OPTI host overlays that shadow image source files
- [ ] Compatibility with existing FRP/Backhaul modes; private-mode migration
- [ ] Recovery, revocation and master-key backup/rotation
- [ ] IR/KH live disposable VPS validation, rollback drills and client tests

**No user commands are required while this PR remains a draft.**
