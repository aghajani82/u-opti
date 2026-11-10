# U-OPTI — Sanaei Docker image origin (RC8 fresh install)

New Sanaei instances created via U-OPTI's existing **3x-UI Docker Management**
or **Smite Foreign → Install Sanaei** now use:

`ghcr.io/aghajani82/3x-ui:main`

This is an image **built and published from the owner's fork**; do not pass
`bash <(curl ...install.sh) dev` to Docker. That command is for direct
(non-container) Linux installation.

## Install prerequisites

Before using on a new host, verify that the fork's **Docker workflow** in
`aghajani82/3x-ui` completed successfully and published the image. If the
image is absent/inaccessible, the existing U-OPTI `docker compose pull` step
fails and installation stops; there is **no fallback to upstream**.

The image tag `:main` is mutable. For repeatable production installs, pin a
tested `ghcr.io/aghajani82/3x-ui@sha256:<verified digest>` at rollout time.

## Safety and scope

- No running Sanaei container, Compose file or DB is automatically replaced by
  this code change. Existing instances keep their recorded Compose image.
- The existing instance IDs, mounts, loopback bindings, Nginx gateway, Smite
  FRP/backhaul paths and rollback behavior remain unchanged.
- After installation on a **new test server**, confirm panel access, sponsor-free
  login/dashboard, 3x-ui DB/API compatibility, Xray and Nginx/443 before RC8
  pairing or backhaul activation.
- The source is checked by `python3 -B tests/test-docker-3xui-fork-image.py -v`.
