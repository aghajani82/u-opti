# U-OPTI 0.16.2 — FRP EASY SETUP + Backhaul START HERE

This describes the menus **actually implemented in main**. Both protocols support a new user-selected XHTTP inbound port and safe base Path, but Smite and Sanaei still have mandatory manual steps. **This is an experimental test-host release, not a production/rollback certification.**

## Install from main on EACH disposable IR/KH host

~~~bash
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/main/install.sh -o /tmp/u-opti-install.sh
bash /tmp/u-opti-install.sh
u-opti
~~~

Docker Management is main menu **7**, Smite Management is Docker menu **5**. Existing installations pinned to a different INSTALL_REF may still update from that ref; a brand new main install always uses main by default.

### Actual common menu

~~~text
Smite Management
1) Private Network Wizard
2) Tunnel Management (FRP / Backhaul / Rathole)
3) Status & Diagnostics
4) Advanced & Legacy Tools
0) Back

Tunnel Management
1) Backhaul — guided Sidecar START HERE
2) FRP — EASY SETUP (Standard IR/KH)
3) Rathole — safe plan only (no installer)
4) Tunnel Control Center — read-only status and routes
0) Back
~~~

On a fresh host the single IR/KH role-selection screen is expected, because Smite is not yet installed. It does not write Smite state.

### Actual FRP beginner menu (choose Tunnel Management → 2)

~~~text
Standard FRP EASY SETUP
This server: ir | Smite: NOT INSTALLED (fresh host)
1) START HERE - Install/check Smite + HTTPS Gateway
2) PORT + PATH - Match KH Sanaei and IR Nginx
3) VERIFY - XHTTP, client settings and real-traffic checklist
4) Advanced - Original detailed steps and recovery
0) Back
~~~

**IR**
1. Confirm Docker Engine+Compose running (installer refuses if missing). Choose **1 START HERE**. It detects missing Smite and asks before calling the existing IR Panel+Node installer. Choose **Standard / Local** in the Smite installer. It checks stored role and running panel+node after installation. If any partial state is detected it refuses a blind reinstall.
2. START HERE *offers* the separate HTTPS/443 Gateway configurator; operator must consent. DNS+TLS/ACME must succeed independently.
3. In Smite web UI create/apply a **FRP TCP tunnel**: IR server / KH client, remote forwarded TCP port matching KH Sanaei inbound; control uses local 7000 routed over IR HTTPS/443 WSS. No automatic creation of this Smite web UI tunnel is claimed.
4. On KH create a VLESS/XHTTP inbound (listen 127.0.0.1, security none, XHTTP mode auto) with your *chosen* port/path. Sample: port 34567 and Path /34567/shop (no trailing slash). Match exact Path between inbound and v2rayN client.
5. Choose **2 PORT + PATH** on IR and enter 34567 + /34567/shop. After explicit confirmation that the Smite FRP TCP tunnel is applied, the wizard attempts to update the managed IR Nginx route and checks exact/prefix publication. It refuses unsafe/colliding paths. This step **does not modify KH**.
6. Choose **3 VERIFY** on IR to probe selected HTTPS Path; verify KH locally using option 3. A positive result needs both HTTP 200 **and X-Padding** header. This is not an authenticated VLESS check; use v2rayN to verify actual upload/download.

**KH**
1. **1 START HERE** opens the existing Foreign Node Standard/HTTPS Smite installer, gated by IR Panel HTTPS readiness, and offers KH HTTPS gateway separately.
2. Use the existing **Docker Sanaei** management to install 3x-UI and create the real VLESS/XHTTP inbound. It is NOT auto-created in the FRP wizard.
3. **2 PORT + PATH** on KH displays the exact matching configuration checklist without writing IR Nginx or KH Sanaei inbound. Use option 2 on IR to publish the actual route.
4. **3 VERIFY** probes the KH loopback XHTTP Path and displays the v2rayN client fields; verify real Internet traffic separately.

**Advanced** preserves original 9 individual functions (Smite install, gateway, status, legacy registration, probe, client settings, repair and timing) but removes them from the beginner menu.

### Actual Backhaul menu (choose Tunnel Management → 1)

~~~text
1) START HERE - Guided Pair + Install (TEST VPS only)
2) Check installation / troubleshoot (read-only)
3) Show VLESS/XHTTP client settings
4) Advanced: manual steps and recovery
0) Back
~~~

- Backhaul uses an **independent Sidecar**. Requires an existing trusted **Smite Standard** role and HTTPS Nginx gateway on IR/KH, plus KH Sanaei with a DIFFERENT XHTTP inbound port and path from FRP.
- Run START HERE separately on **IR first, KH second**. A private shared token is displayed on IR with explicit confirmation and privately pasted into KH; the wizard refuses unsafe existing tokens and does not silently change a running Sidecar.
- Enter the SAME new port and XHTTP Path on both hosts. Admission validates the local Smite role, port ownership, supported Nginx topology and prior install journal; fresh test-host approval, snapshot and provider console are mandatory. Manual marker approval is required and not automatically generated. Never do this on production or an irreplaceable VPS.
- IR may listen on loopback control 3080 before the dynamic data listener; after KH authenticates, the chosen IR loopback data listener should appear. WAITING_FOR_KH_PEER is incomplete but not a reason to reinstall.
- **Check installation** is read-only. Test real authenticated VLESS plus existing FRP clients, KH public bridge guard (13080 must remain private), and reboots separately. Do not rerun START HERE over active or partial state.

### Acceptance boundaries

The verified prior test used FRP 23005 /23005/web and Backhaul 21235 /21235/tt and survived sequential reboots. **A fresh 0.16.2 main-source installation has not yet been field tested by the operator.** Live rollback/reinstall and changing an existing installed Sidecar Path are not certified. Rathole remains safe planning only.
