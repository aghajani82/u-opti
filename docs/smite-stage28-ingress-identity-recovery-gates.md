# Stage 28 — Signed 443 ingress ACL, Node identity continuity & replay recovery HOLD

2026-10-19. Experimental **U-OPTI Draft PR #46** stacked on Draft #45.
Production `main`, release, IR and KH remain unchanged;
`INSTALL_ALLOWED=NO`, `ACTIVATION_GATE=HOLD`.

## New real CI evidence

The Stage27 isolated test now exercises additional **Stage28** negative
scenarios on the *actual* Nginx Stage12 location candidate. It runs only
on a disposable PR runner, with Nginx on `127.0.0.1:443` and the actual
reviewed Smite strict FastAPI Node on `127.0.0.1:18888`.

- **Network-source ACL:** The admitted connection originates from
  `127.0.0.1`; another local TCP peer bound explicitly to
  `127.0.0.2` is **HTTP 403**. Forged `X-Forwarded-For`,
  `X-Real-IP` and RFC `Forwarded` headers asserting the candidate
  allowed Panel IP do **not** override Nginx's socket-peer ACL.
  The blocked HMAC nonce is still unused: when the identical signed
  request arrives on the permitted source, it succeeds once, then
  its replay fails HTTP 401.
- **Pairing identity drift:** Replace the private Node identity fixture
  with a *different Node ID* while keeping the old key. A request
  correctly signed for the original Node must fail HTTP 401. Returning
  the original paired identity in the disposable fixture restores the
  expected one-use behavior.
- **Wrong Node replay database:** Initialize a fresh, private SQLite
  replay database explicitly paired to another Node ID, temporarily
  substitute it for the real fixture DB, and prove that even a valid
  original Node signature receives **503**. Restore the exact original
  DB containing its continuous nonce history, then prove one-time
  signed requests and replay rejection work again.
- Retain real certificate and hostname/SNI verification, unchanged
  HMAC path/query/body semantics, upstream port isolation, rewrite/
  redirect failure and missing-DB `503` tests from Stage27.

These are isolated control-flow tests, **not real IR source routing**
or a distributed SQL/storage recovery benchmark. Both peer addresses
are loopback, not public/provider IPs.

## Replay restore policy — review only, no auto recovery

A same-Node `replay_store_identity` record does **not** prevent an old
snapshot of the correct Node's database from being substituted. Such a
snapshot can lack recently used nonce records, making time-valid HMAC
replays possible. Directory permissions and SQLite schema checks do
not alone provide anti-rollback of historical contents.

The current and next host installer must remain blocked if a replay
store vanishes, loses schema, changes paired ID, or shows unexpected
external replacement. Never respond by formatting a fresh blank DB,
copying arbitrary old SQLite snapshots back into place, or falling
back to legacy/unsigned auth.

Any future **operator-approved** recovery design needs:

1. Capture and verify the exact out-of-band Node pairing identity,
   approved domain/SNI/HTTPS origin and immutable Panel+Node images.
2. Preserve private owner and mode `0700` directories/`0600` DB,
   review trusted snapshot provenance and its WAL/journal companions,
   and retain independent auditable evidence of replay history.
3. Quarantine signed Agent traffic before restoring potentially stale
   replay data. Expire the *entire* worst-case accepted timestamp/
   clock-skew window with verified time synchronization, or complete a
   separate authenticated and audited per-Node key rotation **on both
   ends** before resuming. Neither measure is implemented by this PR.
4. Demonstrate restart/reboot rollback, rejection of old signed traffic,
   ongoing fresh HMAC responses, record provenance and exact original
   identity continuity on disposable VPS images with snapshots.
5. Obtain an explicit, separate production admission and release
   decision. GitHub green CI, a PINNED replay DB or a single 200
   response cannot substitute for this review.

**The Stage28 lab does not install, restore or automatically quarantine
any real SQLite database.** A full host-privilege trust boundary,
permission-safe first enrollment, identity/key rotation, real routing,
remote-source ACL and two-host tests remain outstanding.
