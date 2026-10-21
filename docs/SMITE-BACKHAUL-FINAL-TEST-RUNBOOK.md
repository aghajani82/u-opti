# U-OPTI Backhaul — historical two-existing-VPS Sidecar trial runbook

> **HISTORICAL SIDECAR RUNBOOK — NOT THE FINAL MANAGED CLOSEOUT PATH (2026-10-21).**  
> Keep this file only for audit/history. The current managed closeout path is
> [smite-backhaul-two-host-vps-trial-admission.md](smite-backhaul-two-host-vps-trial-admission.md)
> plus the packaged but menu-disabled `smite-managed-backhaul-host-executor.py`.
> Do not follow the Sidecar assumptions below for the final release candidate.
> Real IR/KH execution still requires separate owner authorization.

**Status: experimental / draft PR #18, not a public release.**

This procedure is for the **two existing IR and KH VPSs only after the
operator has deliberately rebuilt them**, using current, known-good Hetzner
snapshots for recovery. It does NOT instruct rebuilding a production server
without the operator's explicit approval. A third active server is out of
scope and must remain untouched. Do not create or rent extra VPSs solely
because earlier CI documentation referenced two disposable machines.

## 0. Critical limitations and stop conditions

- A provider disk snapshot is a practical whole-server recovery point,
  but restoring it replaces subsequent disk changes. Verify both snapshots'
  timestamps and ability to access the provider console before rebuilding.
  Provider firewall/network policy, DNS, public IP changes and credentials
  held elsewhere should be recorded independently; do not assume a disk
  snapshot includes external provider configuration.
- Rebuilding IR or KH interrupts the currently working Backhaul/FRP
  paths until the affected server's services are re-established.
- This first test **assumes** the previously verified pilot topology
  and domains \`ir.kolbe1.ir\` and \`kh.kolbe1.ir\`. Other domains, paths,
  vhosts or a different port layout require a new reviewed proposal.
- Do not install a second Sidecar alongside an existing named container.
  Never create the deleted Smite-managed Backhaul tunnel just to fill a gap.
- Never paste or print actual token files, TOML, private keys or Xray UUIDs
  into CI output, terminal logs or support chats.
- The standalone trial installer is intentionally **not linked as a one-key
  production wizard action**. It needs a root shell, a manual opt-in
  environment variable, a role-specific confirmation, and two verified
  private candidate directories.
- The test engine still needs an actual disposable/rebuilt VPS exercise
  before general release. CI tests cover mocked host operations plus
  separate isolated real Nginx/Backhaul transport jobs. A green CI result
  alone is not a go-ahead for the rebuild.

## 1. Before either Rebuild — record a recovery point

**On IR and KH, separately**, take a fresh Hetzner snapshot and note
the server identity, IP, public DNS A/AAAA, relevant Hetzner firewall
rules, and SSH console availability. Keep the existing SSH private keys
securely on the operator's own computer; a rebuild does not preserve
local client credentials. Confirm that the unrelated third server and
all of its services remain untouched.

Do NOT rebuild both machines at once. Plan a temporary interruption
of the tunnels and do one server at a time; confirm baseline service
health after each step. If a server cannot be reached after rebuild,
use Hetzner console or the existing snapshot recovery procedure.
A failed experiment is not grounds to keep changing unrelated
existing services.

## 2. Common fresh-host foundation (prerequisite, not Sidecar install)

Use a supported Ubuntu image, Docker, Nginx, CA certificates and
the experimental U-OPTI branch. \`install.sh\` supports
\`U_OPTI_BRANCH=feature/smite-standard-backhaul\`; verify the downloaded
script and source before executing it. Check \`INSTALL_REF\` reflects
the experimental branch so updates do not switch to \`main\`.

**IR (Iran entry):** Existing Smite panel (and Smite node if part of
the baseline), HTTPS/Nginx IR server, FRPS on private
\`127.0.0.1:7000\`, HTTPS backend on \`127.0.0.1:8443\`, with
\`/etc/nginx/conf.d/u-opti-smite-panel-backend.conf\` holding exactly
the reviewed \`ir.kolbe1.ir\` server layout. Public HTTPS:443 must
serve the legitimate website, not expose the internal panel.

**KH (foreign exit):** Existing Smite node and Sanaei/Xray XHTTP
inbound at \`127.0.0.1:56053\`, Nginx HTTPS:443 with the exact known
\`/etc/nginx/sites-available/3xui-kh.kolbe1.ir\` vhost and the
existing numeric port-forwarding rule. Current FRP/Smite baseline
should work before the independent Backhaul trial begins.

If either expected source vhost does not exist after rebuilding,
**STOP**. Do not fabricate it from a sample or disable file checks.
Review the new installation's actual Nginx layout first.

## 3. One private pairing token for the two machines

**IR ONLY — generate exactly once** in a root shell:

\`\`\`bash
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-token.py \
  --generate-ir --confirm CREATE-IR-PAIRING-TOKEN
\`\`\`

Transfer \`/etc/u-opti/backhaul-sidecar/shared.token\` over an
authenticated encrypted SFTP session (e.g. Bitvise) **IR → KH**.
On KH, install it as root-owned, mode 0600, under a root-owned
0700 \`/etc/u-opti/backhaul-sidecar\` directory. Do not paste the
token into chat or put its value on any command line.

**IR and KH, individually — verify only (does not compare the peers):**

\`\`\`bash
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-token.py --verify
\`\`\`

The verified token on KH must be an exact **copy** of IR's token;
generating a second token on KH is incorrect. Token validation
checks private format/ownership only and does not prove parity
between two remote machines.

## 4. Prepare two PRIVATE candidate bundles per host

These commands **do not install anything**; they create private
\`/tmp\` folders with potential secrets. Record their printed
directories locally without copying their contents into a chat.

**IR ONLY:**

\`\`\`bash
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar.py \
  --role ir --token-file /etc/u-opti/backhaul-sidecar/shared.token \
  --ir-domain ir.kolbe1.ir --kh-host kh.kolbe1.ir

python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-nginx-plan.py \
  --role ir --input /etc/nginx/conf.d/u-opti-smite-panel-backend.conf \
  --ir-domain ir.kolbe1.ir --kh-host kh.kolbe1.ir
\`\`\`

**KH ONLY:**

\`\`\`bash
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar.py \
  --role kh --token-file /etc/u-opti/backhaul-sidecar/shared.token \
  --ir-domain ir.kolbe1.ir --kh-host kh.kolbe1.ir

python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-nginx-plan.py \
  --role kh --input /etc/nginx/sites-available/3xui-kh.kolbe1.ir \
  --ir-domain ir.kolbe1.ir --kh-host kh.kolbe1.ir
\`\`\`

For each host, note which \`/tmp/uopti-backhaul-sidecar-*\` and
\`/tmp/uopti-bh-nginx-plan-*\` directories were created.
Never pass a stage directory from IR to the KH role or vice versa.

## 5. Separate admission and manual approval checkpoint

**On the respective IR or KH server**, first run the non-mutating
admission check, substituting only that host's **private directory paths**:

\`\`\`bash
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-admission.py \
  --role ROLE --sidecar-dir /tmp/uopti-backhaul-sidecar-EXAMPLE \
  --nginx-dir /tmp/uopti-bh-nginx-plan-EXAMPLE
\`\`\`

Replace \`ROLE\` with the machine's actual role (\`ir\` or \`kh\`).
The example paths above are placeholders; use the generated paths.
Any \`HOLD\` means stop rather than trying a \`--force\` option.

Before the FIRST real activation, confirm out-of-band: both server
snapshots, exact Nginx vhost paths, certificate/SNI, public KH numeric
port guard, ownership/modes, root console fallback, known container
image digest and existing Smite/FRP/Xray functionality. No one should
run the following commands merely because admission prints PASS.

## 6. Trial activation (ONLY with operator approval after rebuild)

A dedicated CLI \`smite-backhaul-sidecar-live-trial.py\` is available
on the experimental branch; it is **not** a released general installer.
The command is explicitly gated by environment variable and confirmation.

**IR FIRST — only after passing that host's admission:**

\`\`\`bash
UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST \
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-live-trial.py \
  --role ir --install-test \
  --sidecar-dir /tmp/uopti-backhaul-sidecar-EXAMPLE \
  --nginx-dir /tmp/uopti-bh-nginx-plan-EXAMPLE \
  --confirm INSTALL-IR
\`\`\`

Verify IR's Docker container, loopback 3080 and 56053, Nginx syntax,
website and unauthorized \`/channel\` response **before** touching KH.

**KH SECOND — only after IR is healthy and KH passed admission:**

\`\`\`bash
UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST \
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-live-trial.py \
  --role kh --install-test \
  --sidecar-dir /tmp/uopti-backhaul-sidecar-EXAMPLE \
  --nginx-dir /tmp/uopti-bh-nginx-plan-EXAMPLE \
  --confirm INSTALL-KH
\`\`\`

Verify KH's \`127.0.0.1:13080\` loopback bridge, Xray:56053,
certificate validation and public \`/13080/\` **denial**, then
perform a real VLESS/XHTTP client test from Windows or Android.
An HTTP 401 on \`/channel\` and 400 on bare XHTTP GET are useful
local routing observations, **not** proof of a usable tunnel.

## 7. Explicit trial rollback when authorized

The trial engine keeps a private journal and original-vhost backup
under \`/var/lib/u-opti/backhaul-trial/ROLE\`, including after a
successful local install. On a failed install, it attempts to
revert owned files and the sidecar. It refuses automated rollback if
any file content/mode or container ownership has unknown changes.

**On the same server, only after reviewing journal ownership:**

\`\`\`bash
UOPTI_BH_TEST_HOST=I_ACCEPT_REBUILD_TEST_HOST \
python3 /usr/local/lib/u-opti/modules/smite-backhaul-sidecar-live-trial.py \
  --role ROLE --rollback-test --confirm ROLLBACK-ROLE
\`\`\`

Replace \`ROLE\` in \`--role\` with lowercase \`ir\` or \`kh\`;
replace the suffix of the confirmation with uppercase \`IR\` or
\`KH\`. Never run the other server's rollback from this host.

If rollback yields \`HOLD\`, **stop** and inspect the state from the
provider console instead of deleting the journal, forcing
\`docker rm\`, overwriting Nginx, or bypassing the drift checks.
The provider snapshot is the emergency whole-host recovery option.

## 8. Final acceptance criteria (not yet claimed)

The trial is accepted only after **both** separate host runs show:

1. The legit website and existing FRP and Smite routes still work.
2. Backhaul control and KH bridge are private/guarded as intended.
3. Actual Windows/Android VLESS + XHTTP traffic succeeds, not
   merely local HTTP status codes.
4. Both Docker Sidecars survive independent IR and KH reboots with
   \`unless-stopped\` and correct pinned image identity.
5. Full rollback restores original Nginx content **and permissions**
   and removes only the correctly labeled Sidecar.
6. Re-install after rollback behaves predictably, and a failed
   Nginx/Docker activation leaves a recoverable journal.
7. The machine's provider Snapshot remains available until the
   operator explicitly concludes testing.

The external third server is not part of any of these steps.
FRP's existing wizard is separate; Rathole still has NO released
automatic installer. The two-host successful manual pilot should not
be mistaken for this unperformed end-to-end **wizard deployment** test.
