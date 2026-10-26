# NEXT-6 — RC.2-only bundled FRP enrollment field trial (NOT a general installer)

**Status:** Draft PR #48 only. No live IR/KH execution authorized by this document.
**Snapshot evidence:** The operator reports that both disposable IR and KH VPS
snapshots were completed on 2026-10-24. This is an operator report, not an
independent cloud restore attestation. Console restore access must remain available.

## Why this narrow lane exists

After the RC.2 signed connection of `node-ir` and `node-kh`, the user
observed the following on BOTH disposable VPS:

* Node running/healthy, `SMITE_ENGINE_INVENTORY_MODE=managed`.
* Signed Node Identity and KH durable Replay valid, KH connected in Panel.
* The **reviewed immutable Node images** already bundle the SAME root-owned,
  executable, non-group/world-writable `frpc` and `frps`:
  * `frpc` SHA256 `a89129b922f91f1327853a46da65136c52ad421c85315299d333ec06da3f3bbb`
  * `frps` SHA256 `02b50823f330d0486f334d6aa9e448c4d0a26f553a691d167aae8358baab89ee`
* `/etc/smite-node` maps to `/opt/smite-node/config`, a persistent RW
  bind mount on BOTH hosts. Parent is root-owned `0755`, without writable
  group/other permissions.
* Signed inventory returned `not-installed`, because the trusted
  `engine-state/engines.json` is absent on BOTH machines. Smite correctly
  refuses Create Tunnel. FRP files in PATH alone do **not** enroll a core.
* KH Xray test inbound is listening on `127.0.0.1:45121`.

This special **RC.2 field-trial enrollment** is distinct from the future
version-independent FRP host package installer. It does NOT download or
install two independent host binaries, and does NOT claim the requirements
of `smite-managed-frp.py`/the official archive host planner are finished.
It only enables the reviewed exact bundle pair on the two current pinned
images by writing one trusted manifest, with private recoverable journal.

## New branch-only module

`modules/smite-rc2-frp-bundled-enrollment.py`

* `plan`: strictly no writes; check exact IR/KH host, root, running
  pinned Node image, existing signed and managed runtime, identity and
  replay inode/mode, config/identity/replay mounts, immutable **both**
  binary digests, no saved tunnels, absent enrollment and local inventory.
  This does NOT send an HMAC request or consume a replay nonce.
* `enroll`: **requires** root, `UOPTI_SMITE_RC2_FRP_ENROLLMENT=YES`,
  real interactive TTY confirmation `ENROLL-RC2-FRP`, and a shared exclusive
  Backhaul/FRP transaction lock. Re-do preflight plus signed HMAC inventory
  `not-installed` (including replay rejection); create a private journal
  first, create `engine-state` mode `0700`, write `engines.json` mode
  `0600` from exact pinned `frpc`/**`frps`** digest pair; verify signed
  HMAC inventory `ready`; keep identity and Replay storage identity; fsync
  the committed journal. An application-level probe records fresh replay
  nonces, so it legitimately updates the Replay SQLite contents.
* `verify`: refuse partial/uncommitted journal, compare manifest, validate
  signed `ready`. Signed GET records a fresh nonce (not literally
  read-only filesystem activity). It never modifies Compose, engines or
  ports.
* `rollback`: real TTY confirmation `ROLLBACK-RC2-FRP`; decline when any
  content/Identity/Replay inode/tunnel state drift is detected; remove only
  the exact reviewed manifest; independently prove signed `not-installed`;
  remove the private journal after confirmed rollback.
* `recover`: real TTY confirmation `RECOVER-RC2-FRP`; for **uncommitted**
  journal only; refuses to overwrite any changed manifest or protected
  state, restores signed `not-installed`; committed enrollment requires
  separate explicit `rollback`.
* All live actions are **off** until operator stages the *pinned* reviewed
  file by SHA and runs explicitly. Do not run scripts from a moving branch.
  Do not use `python3 - <<'PY'` with interactive prompts.

## Things this lane does NOT authorize or prove

* Neither the public FRP installer, its beginner Wizard, nor a main
  branch merge/release is finished.
* No Docker Compose rewrite, Node restart or other container reboot.
  Verified persistence through actual Node restart is still pending.
* No Nginx/firewall/XHTTP changes; no public ports opened.
* `ready` is only **engine enrollment readiness**, not FRP connectivity.
* A FRP tunnel must not be created before reviewed WSS/443 routing is
  confirmed. The frontend FRP bind default 7000 is **not** permission to
  expose a public listener. The existing RC.2 FRP adapter enables
  loopback `frps` / WSS only with explicit
  `SMITE_FRP_STANDARD_WSS=1`. The reviewed Nginx gateway and signed
  routing must be audited before any tunnel Apply. The policy remains
  public TLS 443 (except SSH) and localhost for other service listeners.
* Backhaul, Sanaei, XHTTP, Grandoptical production, and U-OPTI `main`
  are explicitly out of scope. No automatic install or reboot.

## Acceptance before host execution

1. Entire PR CI green, with the RC.2 FRP offline enrollment/rollback/
   simulated crash tests green.
2. Full reviewed helper SHA fixed and verified before staging on BOTH.
3. Separate owner approval after a successful `plan` on IR and KH.
4. Operator has verified restorable snapshots and emergency consoles.
5. Signed inventory returns `ready` on both after authorized enrollment,
   then exact signed replay/Identity preserved across a separately
   controlled Node recreation.
6. Single 443 FRP WSS path verified before creating a tunnel.
7. Real traffic and tested rollback, then general installer/Wizard
   integration and separately approved release.

**Field-trial safety posture:** No live machine should run `enroll`
based only on a draft PR, a passing local test, or this document.
