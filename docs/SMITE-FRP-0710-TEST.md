# Isolated Smite FRP v0.71.0 trial

**Experimental branch only:** feature/smite-frp-upgrade. Do not merge until live IR/KH tests pass.

## What changes

The pinned Smite v0.1.7 panel and node image digests remain unchanged. U-OPTI downloads the official fatedier/frp v0.71.0 release archive for Linux amd64 or arm64, checks its published SHA256, checks both executable versions, and installs them under /opt/u-opti/smite-frp/v0.71.0.

Before starting each container, the installer adds read-only binary mounts into the existing Smite Compose file. The panel gets frps; IR and KH nodes get both frpc and frps. It verifies the version inside each started container. Other Smite cores, current Nginx TLS/443 settings, EasyTier, and Backhaul are unchanged. No port or tunnel is opened automatically.

## Install on new Ubuntu servers

Both test machines can be abroad, with one playing the IR role and the other KH. Install this experimental branch, not main.

~~~bash
# BOTH SERVERS (IR-role and KH-role)
export U_OPTI_BRANCH=feature/smite-frp-upgrade
curl -fsSL https://raw.githubusercontent.com/aghajani82/u-opti/feature/smite-frp-upgrade/install.sh -o /tmp/u-opti-frp-install.sh
bash /tmp/u-opti-frp-install.sh
~~~

U-OPTI's default Smite menu currently opens a private-network wizard. For the first FRP-only trial, use the Smite Standard-mode installer; do not set up EasyTier or Backhaul merely to reach FRP. Confirm the appropriate Standard-mode entry path before installing Smite.

## Version checks after Smite install

~~~bash
# IR ROLE: PANEL + IR NODE
docker exec smite-panel /usr/local/bin/frps -v
docker exec smite-node /usr/local/bin/frpc -v
docker exec smite-node /usr/local/bin/frps -v

# KH ROLE: FOREIGN NODE
docker exec smite-node /usr/local/bin/frpc -v
docker exec smite-node /usr/local/bin/frps -v
~~~

All checks must report 0.71.0. Stop before creating a tunnel if any reports 0.65.0. The Smite panel is still the control surface: Tunnels -> FRP, not a new U-OPTI FRP submenu.

## Trial sequence

1. Register and verify both Smite nodes in Standard mode.
2. Select unused, separate FRP control/remote ports; allow only what is necessary at provider and OS firewall. Avoid ports used by other services.
3. Run a simple disposable TCP service on KH, create an FRP tunnel in the Smite panel, and verify the IR-facing endpoint.
4. Test stop/start, Smite container recreation, both reboots, and actual transfer behavior.
5. If stable, plan FRP over Nginx/443 separately: raw TCP cannot be proxied as an ordinary Nginx HTTP location.

## Rollback / limitations

This branch is intended for clean test hosts only. Before reverting, stop the test tunnel, remove binary mount entries from the generated Compose files, and recreate containers using the pinned Smite images. Never delete host binary files while Compose references them.

The v0.71.0 FRP binaries are newer than those tested with Smite v0.1.7. Compatibility and end-to-end tunnel performance remain unverified until the real servers are tested. FRP itself is Apache-2.0 licensed: https://github.com/fatedier/frp
