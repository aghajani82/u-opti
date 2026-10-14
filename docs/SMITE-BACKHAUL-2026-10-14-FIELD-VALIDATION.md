# Backhaul independent Sidecar — two-host field validation & handoff (2026-10-14)

> **Scope:** `aghajani82/u-opti`, branch `feature/smite-standard-backhaul`, draft PR #18. This records the operator's **successful TEST VPS** field deployment of the existing experimental installer. It is **NOT** a production release, proof of rollback, or a request to merge into `main`.
>
> **Source of evidence:** observed terminal/menu outputs supplied by the operator on 2026-10-14, plus explicit operator confirmations of real client connectivity and separate reboots. Operator-reported tests are distinguished from the command outputs below. Do not infer that a post-reboot port inventory or automated recovery test was collected.

## Intent and deployment architecture

- Preserve the existing working **Smite panel/node, Standard FRP WSS, Nginx, and 3x-UI/Xray** while testing an **independent Backhaul v0.7.2 Sidecar**.
- The new independent Backhaul tunnel is managed by **U-OPTI**, not by Smite's in-panel Backhaul tunnel creation. **Do not create an overlapping Smite-managed Backhaul tunnel on these ports.** Smite's existing internal `backhaul` process is separate from the new Sidecar.
- **IR (entry):** `ir.kolbe1.ir:443` HTTPS at Nginx; Smite HTTPS backend `127.0.0.1:8443`; independent Backhaul server `127.0.0.1:3080`; FRP server remains at `127.0.0.1:7000`. The sidecar uses the IR Nginx control locations `/channel` and `/tunnel/` plus XHTTP entry `/56053/www/`.
- **KH (exit):** `kh.kolbe1.ir:443` HTTPS at Nginx; independent KH Backhaul client connects via local Nginx TLS-verifying bridge `127.0.0.1:13080` to `ir.kolbe1.ir:443`; KH Xray Backhaul inbound at `127.0.0.1:56053`, distinct from working FRP inbound `127.0.0.1:45561`. Keep the public numeric forwarding restriction on port 13080, including leading-zero variants.
- **End-client test profile:** separate VLESS + XHTTP entry, host/SNI `ir.kolbe1.ir`, port `443`, XHTTP path `/56053/www/`, TLS enabled, credentials from the KH Backhaul-test inbound. Existing FRP profile remains separate.
- Pilot port `56053` and several other topology assumptions are **hard-coded** in the current experimental Sidecar/Nginx planner and checks. **Arbitrary Xray port selection and multiple independently managed Backhaul tunnels are not yet implemented.**

## Verified preparation and safety gates (operator's terminal evidence)

1. **Two new test VPSs**, with U-OPTI feature branch, Smite panel on IR, Smite node and Sanaei/3x-UI on KH. The already-working FRP transport and VLESS/XHTTP client were the preserved baseline. Operator confirmed provider snapshots exist.
2. KH initially failed fresh-host check because the new Backhaul Xray inbound had a mistyped listen address `127..0.1` and Xray failed to start; corrected to `127.0.0.1`, bringing Xray and the original FRP inbound back. This was **not** a Sidecar runtime defect.
3. Both wizard **7 (fresh host)** checks returned `FRESH_HOST_LOCAL_PRECHECK_PASSED`. Offline Nginx **8** plans and private Sidecar **5** candidates were created on each machine; paired candidate **9** checks returned `FRESH_HOST_FILES_AND_LOCAL_PREFLIGHT_PASSED`.
4. IR private pairing token generated with the dedicated tool and securely copied to KH via authenticated SFTP. Each host's token verification returned `PRIVATE_PAIRING_TOKEN_PRESENT_AND_VALID`. SHA-256 of token file was **identical on both hosts** (digest and token deliberately omitted here). Token files must remain private, root-owned and mode `0600`.
5. From KH, `curl -4 --http1.1 --noproxy '*' https://ir.kolbe1.ir/` returned **HTTP 200**, `ssl_verify_result=0`; OpenSSL `-verify_hostname ir.kolbe1.ir -verify_return_error` returned **Verification OK / code 0**. One observed request: TCP ~4.7 ms, TLS ~22.5 ms, total ~28 ms. These are **one HTTPS probe**, not measured tunnel latency.
6. IR Nginx syntax passed; existing Smite backend `127.0.0.1:8443`, upstream `127.0.0.1:8000`, and FRP XHTTP include were observed. KH Nginx syntax passed; expected `kh.kolbe1.ir` HTTPS vhost and numeric forwarding rule were observed. KH emitted **nonfatal** deprecated `listen ... http2` warnings.
7. Trial journal **before first activation** on both hosts: `NO_TRIAL_JOURNAL`. The trial installer initially refused IR activation with `HOLD: Rebuilt disposable-host approval marker missing`. This deliberate safety guard was satisfied **on each disposable test machine only** with root-owned `0600` `/root/.uopti-backhaul-rebuilt-test-host`, containing the exact prescribed approval text. IR and KH approval checks each returned `PASS`.
8. Trial installation via **Tunnel Wizard -> Backhaul -> 10 -> 2**, separate `REBUILT-TEST-VPS` and `INSTALL-IR` / `INSTALL-KH` confirmations, using their own paired stage directories. Both installations returned `TRIAL_INSTALL_LOCAL_CHECKS_PASSED` and kept trial recovery journals.

### Historical offline stage directories (do not treat as durable deployment artifacts)

| Host | Sidecar candidate | Nginx proposal |
|---|---|---|
| IR | `/tmp/uopti-backhaul-sidecar-s23wmeel` | `/tmp/uopti-bh-nginx-plan-4uv4dhs1` |
| KH | `/tmp/uopti-backhaul-sidecar-r8wndx5p` | `/tmp/uopti-bh-nginx-plan-2sn8apny` |

These names only document the original successful install. They are **temporary local paths** and must not be assumed present or reused for future installations/rebuilds. No secret content or private generated config is committed.

## Observed post-install health

| Evidence | IR | KH |
|---|---|---|
| Trial status | `TRIAL_JOURNAL_PRESENT role=ir phase=trial_active` | `TRIAL_JOURNAL_PRESENT role=kh phase=trial_active` |
| Nginx `nginx -t` | successful | successful, nonfatal HTTP/2 deprecation warning |
| Independent Docker container | `uopti-backhaul-sidecar-ir`, Up | `uopti-backhaul-sidecar-kh`, Up |
| Existing Smite | `smite-panel` and `smite-node` healthy | `smite-node` healthy; `3xui-01` Up |
| Listening sockets | public :443; loopback :8443, :7000, :3080 | public :443; loopback :13080, :56053, :45561 |
| Wizard diagnostic | IR sidecar and listening ports observed via command output | `KH Sidecar: running, auto-start`; `Nginx bridge 13080: 127.0.0.1:13080`; `Xray 56053: 127.0.0.1:56053`; `Bridge channel: HTTP 401` |

**Interpretation:** unauthenticated `/channel` HTTP 401 is **not** proof of authenticated WS. Likewise a bare XHTTP GET/HTTP 400 is **not** proof of user traffic.

### Actual traffic and reboot results — operator confirmations

- Working pre-existing **FRP VLESS/XHTTP** profile was retested by the operator **after installation on IR** and **again after installation on KH**, both times reported **working**.
- Operator separately tested the **new Backhaul VLESS/XHTTP** client configuration and reported it **working without creating a Backhaul tunnel inside Smite**. This matches independent U-OPTI ownership; it should not be conflated with Smite tunnel management.
- On **2026-10-14**, operator reports rebooting **both test hosts one after the other** and retesting configurations: **all tested profiles worked without issue**. A new post-reboot `docker ps`/`ss`/journal/log transcript was **not captured** in this report; do not claim such logs or more extensive failover testing.

## Remaining acceptance gates — before production/main merge

- **Rollback and reinstall remain untested in the live two-host deployment.** The journal and original Nginx backup exist under `/var/lib/u-opti/backhaul-trial/ROLE`; use the guarded `10 -> 3` rollback only with explicit operator consent, backup/console availability and proper ownership review. A `HOLD` is a stop condition. Never delete journals or manually force rollback.
- Verify **KH public numeric path blocking**, especially `/13080/` and leading-zero variants, with an actual external HTTPS request; local loopback binding alone is not sufficient.
- Obtain **post-reboot read-only inventories** for both hosts (trial status, Docker, Nginx and sockets) when convenient, despite operator-confirmed successful traffic.
- Validate a **failed installation recovery** and **rollback -> clean reinstall** on disposable machines before calling the trial engine production-ready.
- The **current experimental UX is too complex**: Backhaul has ten separate wizard options, two-stage candidate directories and repeated manual gates. Simplify into a safe automatic wizard with role detection, automatic staging, conflict/health checks and clearly identified install/status/rollback operations; do not silently remove critical confirmations.
- Support configurable Xray port and multi-tunnel isolation; do not assume merely changing `56053` in one file suffices.
- Later provide **central management in Smite** while preserving U-OPTI Sidecar ownership and standalone operation. Smite's current in-panel tunnel creation does **not** control this independent Sidecar. Do not let two orchestrators modify one tunnel.
- Keep the existing working **FRP** setup and its wizard untouched unless separately authorized. Rathole remains a separate, not-yet-validated workflow.

## Continuation instructions for a future chat or maintainer

1. Begin with this document plus `docs/SMITE-BACKHAUL-FINAL-TEST-RUNBOOK.md` and PR #18, **not** a reconstructed summary of the conversation.
2. Current state as of operator's last report: both test Sidecars installed, `phase=trial_active` previously seen on each host; FRP and new Backhaul client profiles work **after separate host reboots**. Do **not** reinstall or roll back either host unprompted.
3. Highest priority next: **durable GitHub handoff and menu/wizard cleanup**, then supervised recovery/rollback qualification before production. No need to repeat already completed token transfer, candidate generation, installation or basic VLESS tests just to reconstruct context.
4. Keep PR #18 **draft on `feature/smite-standard-backhaul`** until code review and untested acceptance gates are completed; **no premature merge into `main`**.
5. For ordinary status checks (read-only, per role): `python3 -B /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-live-trial.py --role ir|kh --status`, `nginx -t`, `docker ps`, `ss -lntp`. Never print pairing token, private TOML, UUID, passwords, or certificate keys to chat/CI.
6. The exact initial endpoints/ports/vhosts are **pilot-specific**; avoid presenting them as flexible production defaults. Maintain recoverability and explicit operator consent for any write, Nginx reload, or tunnel management change.

**Validation label:** `TWO_TEST_HOSTS_LOCAL_INSTALL_PASS + OPERATOR_REAL_FRP_BACKHAUL_TRAFFIC_PASS + OPERATOR_SEQUENTIAL_REBOOT_PASS; ROLLBACK_UNTESTED / PRODUCTION_NOT_APPROVED`.
