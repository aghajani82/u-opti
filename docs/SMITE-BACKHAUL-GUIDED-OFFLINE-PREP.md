# Independent Backhaul — guided private OFFLINE preparation (phase 2)

**Status:** experimental branch only; no live installation or rollback is performed by this feature. This is a smaller, safer first step towards the requested beginner-friendly one-wizard workflow.

**Current field-validation source:** `docs/SMITE-BACKHAUL-2026-10-14-FIELD-VALIDATION.md` (both TEST hosts successfully ran FRP and independent Backhaul traffic after sequential reboots, according to operator). **Do not re-run preparation on those already-installed hosts**: the new wizard should `HOLD` for an existing Sidecar. Do not confuse Smite-managed Backhaul processes with the independent Sidecar.

## Menu path

```text
Smite Management
 -> 2) Tunnel Management
 -> 1) Backhaul
 -> 4) Experimental setup & recovery tools
 -> 1) Guided one-step PRIVATE/OFFLINE prepare (fresh host)
```

The user supplies **IR HTTPS domain** and **KH upstream/Xray host** once, and explicitly types `PREPARE-PRIVATE-OFFLINE`. The tool then:

1. Requires root, role IR/KH and valid lowercase FQDNs; checks that a privately provisioned root-owned pairing token already exists (no token is printed or passed as a CLI parameter).
2. Runs the existing **fresh-host** Docker/Nginx/listener/Sidecar-readiness check. An already installed Sidecar or occupied reserved port is an intentional **HOLD**.
3. Uses existing, unmodified Sidecar and Nginx generators to create **two private, role-matched offline proposals**. No repeated domain prompting.
4. Checks their identity, exact content hashes, on-host Nginx source integrity, ownership, file modes, created-target absence and fresh-host admission through the existing gate.
5. Returns one **staging success** code and the paths to the TWO private `/tmp` directories, *not* their contents. On error the newly created, owned 0700 stage directories are removed where safe. Token/config/vhost contents are never printed.
6. Never writes to `/etc`, Docker, Nginx, Smite, FRP or Xray. The staged folders are **not durable recovery backups** and are not deployment authorization.

**Important limitations:** The shared token still requires prior secure IR generation and authenticated out-of-band transfer to KH. Guided preparation currently **does not** create a multi-host pairing channel or an installed tunnel. The separately gated TEST-VPS installer still asks for the two returned proposal directory paths, an exact disposable-host approval marker and role-specific confirmation. These safeguards remain unchanged pending separate field rollback testing.

This feature deliberately retains the original manual Sidecar/Nginx/admission commands under **Advanced manual / legacy tools**. It does not change the working FRP or Private Network menus.

## CLI entry point for disposable fresh hosts (not currently installed hosts)

```bash
python3 -B /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-guided-prep.py \
  --role ir \
  --ir-domain ir.kolbe1.ir \
  --kh-host kh.kolbe1.ir \
  --prepare-only --confirm PREPARE-PRIVATE-OFFLINE
```

On KH use `--role kh`; first securely transfer and verify the same pairing token. These domain values illustrate the **currently pinned test topology**, not an arbitrary-production-host promise; the KH Nginx input path is presently hard-coded for `kh.kolbe1.ir`.

## CI and remaining work

- Hermetic mocked-host tests cover both roles, refusal before staging if installed or token invalid, admission HOLD and cleanup, explicit confirmation, input rejection and preventing secret text from leaking into CLI output.
- `tests/test-smite-tunnel-wizard.sh` covers the new guided route **and** retains direct FRP, read-only Backhaul, legacy manual admission and guarded trial routes.
- `tests/test-smite-backhaul-package-closure.py` verifies a fresh U-OPTI install/update can import the guided module and its transitive dependencies without the repository checkout.
- Actual runtime/reboot testing of **this guided-preparation feature on fresh disposable hosts** remains to be performed. CI is not evidence of a real install, restoration or authenticated data path.
- **Next:** supervised trial rollback and reinstall qualification; external KH bridge numeric-path check; then a separate audited plan for integrating staging, explicit approval and live deployment behind one wizard, plus selectable Xray ports and centrally managed Smite UI. Keep PR #18 draft until reviewed.

No pair token, token hash, UUID, key, or private staged TOML/Nginx content belongs in GitHub documents or chat.
