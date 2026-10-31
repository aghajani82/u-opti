# Stage15 — Physical Passkey browser rehearsal in an isolated HTTPS lab

**Status: PREPARATION ONLY — NOT EXECUTED. NO LIVE APPROVAL OR FRP RELEASE.**

This is an operator acceptance procedure, **not** an installation recipe
for IR/KH or `approve.kolbe1.ir`. A green source CI or fixture signature
does not demonstrate a physical authenticator, browser UV, TLS trust,
recovery, or live IR/KH compatibility.

## Separate lab boundary (no production reachability)

Use a disposable standalone computer/VM with no routes, credentials,
containers, volumes, backups, sockets or trusted grants copied from IR,
KH, or Grandoptical. Do not execute lab setup on an active server.
Do not connect this lab to the production Panel or its broker. Neither
`smite-node` nor FRP/FRPC may run there. No 0.0.0.0 listeners.

The example reviewed lab policy is
`docs/examples/stage15-passkey-browser-lab.json`; verify it with the
**offline library** `modules/smite-stage15-passkey-lab-gate.py`
(or the corresponding CI tests). Passing that policy only confirms a
static manifest, **not** that the lab is deployed or isolated in fact.
Keep `broker=disabled`, `grant_writer=disabled`,
`signed_ir_kh=synthetic-only`, and `route_publication=disabled`.

For a later *separately approved* physical test on the disposable host:
1. Select exactly `https://passkey-lab.test` as the WebAuthn RP
   Origin, with `https://panel-lab.test` as an unrelated *example*
   Panel Origin; neither should have public DNS records. Resolve each
   hostname to `127.0.0.1` **only within the disposable test system**.
   The browser must see a locally trusted CA-issued HTTPS certificate
   valid for `passkey-lab.test`. No bypassing browser certificate warnings,
   self-signed invalid cert exceptions, public listeners, or port-forwarding.
   Do not reuse `approve.kolbe1.ir`, existing LE certificates, or a
   production Nginx configuration.
2. Use a *fresh disposable* credential and approval ledger DB with
   test-only records. The test HTTP Unix-socket service may only use
   synthetic verification evidence and an in-memory **no-op grant writer**
   that cannot resolve to `install_grant`. It must never have a live
   broker socket, Panel DB mount, signing/HMAC secrets or network route to
   IR/KH. Review the actual process bindings/firewall before starting it.
   **No production service launcher is authorized for this lab.** The
   existing CI UDS service uses a deterministic fake authenticator;
   it is not a substitute for a physical browser adapter.
3. Operator with two **physically independent** authenticators (not two
   synced copies of one credential) registers primary and backup using
   two separate, short-lived, root-console one-time tickets in the
   disposable lab. Confirm real browser User Verification (PIN/biometric)
   for each and confirm the stored credential identifiers differ. Do not
   share PINs, credentials, private keys or tickets in issue comments/logs.
4. Observe positive test: primary authenticates for a *test-only*
   pending review; a valid signature/UV may advance the disposable lab
   ledger but **must never issue a TrustedGrant, publish XHTTP, touch
   Nginx routes or create a child**. Repeat with backup after reopening
   the credentials DB. A browser credential picker alone is not
   successful WebAuthn authentication.
5. Negative tests: wrong HTTPS Origin/RP ID, tampered assertion,
   missing user verification, reused/expired challenge or enrollment
   ticket, revoked credential, stale/no test evidence, failed/no backup,
   and unexpected HTTP/cookie/forwarded-header handling must HOLD
   without any grant. A challenge failure consumes that challenge;
   it does not silently retry or approve.
6. Recovery: register the spare first, verify it independently, revoke
   the primary in the disposable store, verify spare authentication
   still works and a duplicate revocation fails. Attempt to revoke the
   *last* active key and confirm
   `LAST_PASSKEY_RECOVERY_REQUIRED`. If the only key is compromised,
   the correct incident action is to disable/quarantine the dedicated
   approval service under a separately reviewed procedure, **not** to
   continue accepting the compromised credential or hand-edit SQLite.
7. After testing, stop/remove only the disposable lab service and
   destroy its temporary state and local trust anchor according to
   operator policy. Confirm test host entries/certs were **never**
   installed on IR/KH/Grandoptical and no live broker grants/routes
   or Node restart occurred. Preserve sanitized outcome only.

## Disposable standalone browser test harness (source-only preview)

A separate **test-only** implementation exists in
`tests/labs/stage15-passkey-https-lab.py`, with a small HTML/JS browser
front end beside it. It uses the pinned `fido2==2.0.0` server verifier,
performs real WebAuthn `register_begin/register_complete` and
`authenticate_begin/authenticate_complete` calls, requires UV, consumes
short-lived challenges before verification, and stores at most two test
credential public keys **only in process memory**. It exposes test
counters and `LAB_AUTHENTICATED_NO_GRANT`, **not** any TrustedGrant.

The standalone process cannot speak to Smite Panel, IR/KH Node, FRP,
Broker or Nginx: it has no such imports/config/credentials/paths, no
persistent DB, and no outbound network calls. It serves only
`127.0.0.1:443` over HTTPS, with exact WebAuthn Origin
`https://passkey-lab.test` and Host admission. It requires explicit
`--isolated-lab`, a **separately generated** test-only certificate and
private key, and `I_CONFIRM_DISPOSABLE_OFFLINE_LAB`. Known production
hostnames are rejected. A confirmation string cannot prove isolation;
verify the actual disposable VM network and filesystems yourself first.
Never run the harness on IR/KH/Grandoptical or on a host with access
to their data, secrets or network.

After the operator separately provisions a disposable *offline* VM and
its locally trusted test-only TLS certificate/hostname, the generic
launch form **on the disposable VM ONLY** is:

```text
python3 tests/labs/stage15-passkey-https-lab.py --isolated-lab \
  /absolute/path/to/LAB_ONLY_certificate.pem \
  /absolute/path/to/LAB_ONLY_privatekey.pem \
  I_CONFIRM_DISPOSABLE_OFFLINE_LAB
```

This is **not** a command to run now on IR or KH. Binding privileged
port 443 may require separate operator-selected VM permission; do not
change production Nginx, firewall or systemd to make it work. The
test-only hostname must resolve to loopback solely on the disposable
host, and the browser must trust the disposable CA **without a TLS
warning bypass**. Do not use an existing production LE certificate.
Open `https://passkey-lab.test` in the disposable browser, register
two separate physical authenticators, and authenticate with each.
The credential public keys exist only in lab RAM but a newly created
test RP credential can remain in the authenticator until the operator
manually deletes it. Never put any real secret in the test harness.

CI tests only mock the FIDO2 cryptography and issue local ephemeral-port
HTTP requests to inspect Origin, Host, cookie, CSRF and replay denial.
A passing CI **does not establish** physical verification, local TLS
trust, hardware independence, or isolation of the real VM. When
`fido2==2.0.0` or the browser lacks required WebAuthn methods, the
manual lab must HOLD; never replace production proof with the fake.
This harness does not implement the production root ticket / approval
UI and must not be used to evaluate a live Passkey enrollment release.

## Acceptance record — explicitly pending

| Check | Source CI status | Physical/browser status |
| --- | --- | --- |
| Exact HTTPS Origin, separate Panel Origin | Unit policy checked | **NOT RUN** |
| Trusted local TLS on disposable host | Config-only contract | **NOT RUN** |
| Two physically independent authenticators | Synthetic mock only | **NOT RUN** |
| UV challenge verification with real hardware | Synthetic mock only | **NOT RUN** |
| Backup works after DB reopening | Synthetic mock only | **NOT RUN** |
| Last-key revocation guard | Isolated test | **NOT RUN** |
| No live grant, FRP, Node, or production changes | Static contract only | **NOT VERIFIED ON LAB** |
| Passkey on actual IR approval hostname | No live work permitted | **BLOCKED** |
| Fourth XHTTP tunnel publication | No live work permitted | **BLOCKED** |

**Gate after rehearsal:** Even a full lab PASS authorizes **no**
production deployment. Signed IR/KH runtime evidence, host credential
provenance, durable nonce, correct TLS/UDS configuration, signed images,
and no-restart constraints need an independently approved rollout or an
explicit maintenance decision. Do not silently upgrade active Node
containers or touch Grandoptical.
