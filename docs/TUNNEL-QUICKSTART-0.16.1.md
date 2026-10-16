# FRP + Backhaul — beginner quick start (v0.16.1 TEST workflow)

These two tunnels use separate forwarding ports and XHTTP base Paths. **Do not reuse an existing inbound or overlap active Nginx routes.** The two-host test validated FRP port 23005 /23005/web and Backhaul port 21235 /21235/tt. Those values are **examples only**: choose your own ports and Paths during each new install.

## Fresh installation from the original main branch

On **BOTH IR and KH** (as root, on disposable/test VPSs with snapshots and emergency console access):

~~~bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/uopti-install.sh
bash /tmp/uopti-install.sh
u-opti
~~~

If not reinstalling, use U-OPTI main menu option **8 Update U-OPTI**. Check INSTALL_REF: an existing test-branch installation remains pinned to its chosen branch and is NOT automatically redirected to main. To test main from scratch, use a fresh disposable VPS; never overwrite a working server solely to switch branches.

## Shared prerequisites (both tunnels)

1. **IR role**: Smite Standard Panel+Node, HTTPS domain with valid TLS certificate and Nginx TCP/443 entry.
2. **KH role**: Smite Standard Foreign Node and Docker Sanaei 3x-UI with a separate VLESS/XHTTP inbound for each tunnel, listening on 127.0.0.1 (security none; TLS terminates on IR).
3. Choose a new KH inbound TCP port (1024–65535 excluding reserved/colliding ports) and custom slashless XHTTP base Path, such as /21235/tt or /assets/connect. The Xray inbound and corresponding client must use the exact same Path. The OPTIONS request may append a trailing slash.
4. Do not open public FRPS/Backhaul control or Xray data ports. Keep the existing FRP and production Nginx configuration intact.

## FRP — keep Smite TCP tunnel separate from its HTTPS Path

Open Docker Management → Smite Management → **2 Tunnel Management** → **2 FRP**. Finish prerequisites for IR and KH. Create and *apply* a Standard **FRP TCP** tunnel in the Smite web UI: IR = server, KH = client; forwarded data port equals KH Sanaei inbound port. FRPS control uses localhost 7000, reached via the HTTPS gateway; do not publish raw 7000.

**IR**: FRP wizard **Step 5** registers the chosen forwarded port and exact XHTTP Path in the IR Nginx gateway. This writes only the IR path registry and reconciles the managed include with rollback if Nginx rejects it. Path is not active until the wizard verifies the exact/prefix Nginx locations.

**KH**: FRP wizard **Step 5 is a CHECKLIST ONLY**; manually configure the KH Sanaei VLESS/XHTTP inbound Path to match. No KH action silently updates the IR gateway.

FRP wizard **Step 6** checks the local XHTTP OPTIONS handler; **Step 7** shows client profile hints; **Step 9** reports response timing (not throughput). Verify actual authenticated VLESS traffic in v2rayN, with IR domain:443, TLS/SNI IR domain, ALPN http/1.1, mode auto, and selected Path.

## Backhaul — one beginner entry, run on both hosts

Open Docker Management → Smite Management → **2 Tunnel Management** → **1 Backhaul** → **1 START HERE**.

The same **START HERE** flow is run separately on each disposable IR and KH test host, using two Bitvise terminals:
- IR: when the private pairing token is missing, the wizard shows a long-lived pairing code after explicit confirmation. Transfer it privately (never into chats, support logs, screenshots, shell arguments).
- KH: paste the private code at the hidden prompt, or verify an already paired token. The wizard never overwrites an existing private token.
- On each host: the wizard asks IR/KH domain, **your chosen data port** and **your chosen XHTTP Path**, checks Smite role, Nginx topology, token/port ownership, and prior journal state, then only installs on the currently selected server **after explicit test-host approval**.
- A root-owned 0600 test-host approval marker with the exact disposable-host consent text is **not** created automatically. The snapshot and provider emergency console are operator prerequisites. Do not create this marker on a production or irreplaceable host.
- The installer refuses existing or partial Sidecar trial state; after a HOLD, use option **2 Check installation**, never blindly reinstall, rebuild or force rollback.
- Expected success on **each** host is GUIDED_TEST_HOST_INSTALL_LOCAL_CHECKS_PASSED. Check both trial journals have phase trial_active and the installed Sidecar health separately.

Backhaul IR port 3080 is local control; the **data port on IR may not listen until KH's Backhaul client authenticates**. The read-only audit reports WAITING_FOR_KH_PEER as incomplete (not a false PASS). After KH connects, re-check IR and the chosen data port.

Do not create a Smite UI Backhaul tunnel on the same ports as independent Sidecar. Verify denied public KH bridge forwarding on port 13080.

## Real acceptance checks

1. Nginx -t and HTTPS certificate/SNI on both hosts.
2. IR Backhaul local listener 3080; after KH connects also the selected data port. KH Xray local OPTIONS of the selected Path returns HTTP 200 with expected handler response.
3. BOTH trial journals and installed read-only checks pass. Check sanitized Docker status; never send shared tokens or VLESS UUIDs.
4. Test **both authenticated FRP and Backhaul v2rayN clients**, including upload/download, not just HTTP OPTIONS, and that FRP remains unaffected.
5. Reboot KH then IR **separately**, with console access, and repeat real client tests.
6. **Keep production rollout and PR qualification separate**: rollback/reinstall after partial deployment, standalone non-Smite Backhaul, and safe in-place Path changes of existing Sidecars are not proven by this quick start.
