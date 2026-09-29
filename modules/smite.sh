#!/bin/bash

# U-OPTI - Smite 443 Integration
# Persistent compatibility layer for the tested Smite 443 architecture.

SMITE_PANEL_DIR="${SMITE_PANEL_DIR:-/opt/smite}"
SMITE_NODE_DIR="${SMITE_NODE_DIR:-/opt/smite-node}"
SMITE_OVERLAY_DIR="${SMITE_OVERLAY_DIR:-/opt/u-opti-smite}"
SMITE_PANEL_COMPOSE="$SMITE_PANEL_DIR/docker-compose.yml"
SMITE_NODE_COMPOSE="$SMITE_NODE_DIR/docker-compose.yml"

smite_require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "ERROR: Docker is not installed."
        return 1
    fi
}

smite_container_exists() {
    docker inspect "$1" >/dev/null 2>&1
}

smite_container_running() {
    [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

smite_wait_healthy() {
    local container="$1"
    local timeout="${2:-60}"
    local elapsed=0
    local state health

    while [ "$elapsed" -lt "$timeout" ]; do
        state="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)"

        if [ "$state" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "none" ]; }; then
            return 0
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    return 1
}

smite_show_status() {
    clear
    echo "======================================"
    echo "          Smite 443 Status"
    echo "======================================"
    echo

    if smite_container_exists smite-panel; then
        echo "Smite Panel : $(docker inspect -f '{{.State.Status}}' smite-panel 2>/dev/null)"
    else
        echo "Smite Panel : Not installed on this server"
    fi

    if smite_container_exists smite-node; then
        echo "Smite Node  : $(docker inspect -f '{{.State.Status}}' smite-node 2>/dev/null)"
    else
        echo "Smite Node  : Not installed on this server"
    fi

    echo
    echo "Panel path  : $SMITE_PANEL_DIR"
    echo "Node path   : $SMITE_NODE_DIR"
    echo "Overlay path: $SMITE_OVERLAY_DIR"
    echo

    if [ -f "$SMITE_OVERLAY_DIR/panel/node_client.py" ]; then
        echo "Panel compatibility overlay : Present"
    else
        echo "Panel compatibility overlay : Not prepared"
    fi

    if [ -f "$SMITE_OVERLAY_DIR/node/panel_client.py" ]; then
        echo "Node compatibility overlay  : Present"
    else
        echo "Node compatibility overlay  : Not prepared"
    fi

    echo
    read -rp "Press Enter to return..."
}

smite_patch_node_runtime() {
    smite_container_running smite-node || {
        echo "ERROR: smite-node is not running."
        return 1
    }

    docker exec -i smite-node python - <<'PY'
from pathlib import Path


def replace_once(path, old, new, marker, label):
    p = Path(path)
    s = p.read_text()
    if marker in s:
        print(f"{label}: already patched")
        return
    if old not in s:
        raise SystemExit(f"ERROR: {label}: expected upstream block not found; refusing unsafe patch")
    p.write_text(s.replace(old, new, 1))
    print(f"{label}: patched")

panel_client = "/app/app/panel_client.py"
replace_once(
    panel_client,
    '''        panel_api_port = settings.panel_api_port
        
        panel_api_url = f"http://{panel_host}:{panel_api_port}"
''',
    '''        panel_api_port = panel_hysteria_port or settings.panel_api_port
        panel_api_scheme = "https" if str(panel_api_port) == "443" else "http"
        
        panel_api_url = f"{panel_api_scheme}://{panel_host}:{panel_api_port}"
''',
    'panel_api_scheme = "https" if str(panel_api_port) == "443" else "http"',
    "node registration HTTPS/443",
)

replace_once(
    panel_client,
    '''            panel_api_port = settings.panel_api_port
            panel_api_url = f"http://{panel_host}:{panel_api_port}"
''',
    '''            if "://" in self.panel_address:
                _, rest = self.panel_address.split("://", 1)
            else:
                rest = self.panel_address

            if ":" in rest:
                _, panel_api_port = rest.rsplit(":", 1)
            else:
                panel_api_port = settings.panel_api_port

            panel_api_scheme = "https" if str(panel_api_port) == "443" else "http"
            panel_api_url = f"{panel_api_scheme}://{panel_host}:{panel_api_port}"
''',
    '_, panel_api_port = rest.rsplit(":", 1)',
    "node FRP-status HTTPS/443",
)

core = "/app/app/core_adapters.py"
replace_once(
    core,
    '''            else:
                forward_host = remote_ip
                forward_port = port_num
                forward_is_ipv6 = use_ipv6
''',
    '''            else:
                forward_host = remote_ip
                remote_port = spec.get("remote_port")
                if remote_port is not None and len(ports) == 1:
                    forward_port = int(remote_port) if isinstance(remote_port, (int, str)) and str(remote_port).isdigit() else remote_port
                else:
                    forward_port = port_num
                forward_is_ipv6 = use_ipv6
''',
    'remote_port = spec.get("remote_port")',
    "GOST remote_port",
)

replace_once(
    core,
    '''    async def cleanup(self):
        """Cleanup all tunnels"""
        for tunnel_id in list(self.active_tunnels.keys()):
            await self.remove_tunnel(tunnel_id)
''',
    '''    async def cleanup(self):
        """Stop active tunnel processes without deleting persisted configurations."""
        for tunnel_id in list(self.active_tunnels.keys()):
            try:
                adapter = self.active_tunnels[tunnel_id]
                adapter.remove(tunnel_id)
            except Exception as e:
                logger.warning(f"Failed to stop tunnel {tunnel_id} during shutdown: {e}")
            finally:
                self.active_tunnels.pop(tunnel_id, None)
''',
    "Stop active tunnel processes without deleting persisted configurations.",
    "node tunnel persistence cleanup",
)
PY
}

smite_patch_panel_runtime() {
    smite_container_running smite-panel || {
        echo "ERROR: smite-panel is not running."
        return 1
    }

    docker exec -i smite-panel python - <<'PY'
from pathlib import Path


def replace_once(path, old, new, marker, label):
    p = Path(path)
    s = p.read_text()
    if marker in s:
        print(f"{label}: already patched")
        return
    if old not in s:
        raise SystemExit(f"ERROR: {label}: expected upstream block not found; refusing unsafe patch")
    p.write_text(s.replace(old, new, 1))
    print(f"{label}: patched")

replace_once(
    "/app/app/routers/tunnels.py",
    '''                    gost_spec = {
                        "ports": ports,
                        "remote_ip": remote_ip,
                        "type": db_tunnel.type,
                        "use_ipv6": use_ipv6
                    }
''',
    '''                    gost_spec = {
                        "ports": ports,
                        "remote_ip": remote_ip,
                        "type": db_tunnel.type,
                        "use_ipv6": use_ipv6
                    }

                    remote_port = db_tunnel.spec.get("remote_port")
                    if remote_port is not None:
                        gost_spec["remote_port"] = remote_port

                    forward_to = db_tunnel.spec.get("forward_to")
                    if forward_to:
                        gost_spec["forward_to"] = forward_to
''',
    'gost_spec["remote_port"] = remote_port',
    "panel GOST remote_port forwarding",
)

replace_once(
    "/app/app/node_client.py",
    '''        # FRP is not enabled or not available - use HTTP
        node_address = node.node_metadata.get("api_address", f"http://localhost:8888") if node.node_metadata else f"http://localhost:8888"
        if not node_address.startswith("http"):
            node_address = f"http://{node_address}"
        logger.info(f"[HTTP] Using direct HTTP to communicate with node {node.id} at {node_address}")
        return (node_address, False)
''',
    '''        # FRP is not enabled or not available.
        # Prefer an explicit control address when configured.
        if node.node_metadata:
            node_address = (
                node.node_metadata.get("control_address")
                or node.node_metadata.get("api_address")
                or "http://localhost:8888"
            )
        else:
            node_address = "http://localhost:8888"

        if not node_address.startswith("http"):
            node_address = f"http://{node_address}"

        logger.info(f"[HTTP] Using node control address for node {node.id}: {node_address}")
        return (node_address, False)
''',
    'node.node_metadata.get("control_address")',
    "panel control_address",
)
PY
}

smite_prepare_overlays() {
    smite_require_docker || return 1

    mkdir -p "$SMITE_OVERLAY_DIR/panel" "$SMITE_OVERLAY_DIR/node"
    chmod 0755 "$SMITE_OVERLAY_DIR" "$SMITE_OVERLAY_DIR/panel" "$SMITE_OVERLAY_DIR/node"

    if smite_container_exists smite-panel; then
        smite_patch_panel_runtime || return 1
        docker cp smite-panel:/app/app/node_client.py "$SMITE_OVERLAY_DIR/panel/node_client.py" || return 1
        docker cp smite-panel:/app/app/routers/tunnels.py "$SMITE_OVERLAY_DIR/panel/tunnels.py" || return 1
        chmod 0644 "$SMITE_OVERLAY_DIR/panel/node_client.py" "$SMITE_OVERLAY_DIR/panel/tunnels.py"
    fi

    if smite_container_exists smite-node; then
        smite_patch_node_runtime || return 1
        docker cp smite-node:/app/app/panel_client.py "$SMITE_OVERLAY_DIR/node/panel_client.py" || return 1
        docker cp smite-node:/app/app/core_adapters.py "$SMITE_OVERLAY_DIR/node/core_adapters.py" || return 1
        chmod 0644 "$SMITE_OVERLAY_DIR/node/panel_client.py" "$SMITE_OVERLAY_DIR/node/core_adapters.py"
    fi

    echo "Smite compatibility overlays prepared successfully."
}

smite_patch_compose_mounts() {
    local timestamp
    timestamp="$(date +%Y%m%d-%H%M%S)"

    if [ -f "$SMITE_PANEL_COMPOSE" ] && [ -f "$SMITE_OVERLAY_DIR/panel/node_client.py" ]; then
        cp -a "$SMITE_PANEL_COMPOSE" "$SMITE_PANEL_COMPOSE.u-opti-$timestamp.bak" || return 1
        python3 - "$SMITE_PANEL_COMPOSE" "$SMITE_OVERLAY_DIR" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
overlay = sys.argv[2]
s = path.read_text()
mount = f"      - {overlay}/panel/node_client.py:/app/app/node_client.py:ro\n"
if mount not in s:
    marker = "      - ./docker-compose.yml:/app/config/docker-compose.yml:ro\n"
    if marker not in s:
        raise SystemExit("ERROR: panel compose volume marker not found; refusing unsafe edit")
    extra = (
        marker
        + f"      - {overlay}/panel/node_client.py:/app/app/node_client.py:ro\n"
        + f"      - {overlay}/panel/tunnels.py:/app/app/routers/tunnels.py:ro\n"
    )
    s = s.replace(marker, extra, 1)
    path.write_text(s)
print("Panel compose mounts: OK")
PY
    fi

    if [ -f "$SMITE_NODE_COMPOSE" ] && [ -f "$SMITE_OVERLAY_DIR/node/panel_client.py" ]; then
        cp -a "$SMITE_NODE_COMPOSE" "$SMITE_NODE_COMPOSE.u-opti-$timestamp.bak" || return 1
        python3 - "$SMITE_NODE_COMPOSE" "$SMITE_OVERLAY_DIR" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
overlay = sys.argv[2]
s = path.read_text()
mount = f"      - {overlay}/node/panel_client.py:/app/app/panel_client.py:ro\n"
if mount not in s:
    marker = "      - node-data:/var/lib/smite-node\n"
    if marker not in s:
        raise SystemExit("ERROR: node compose volume marker not found; refusing unsafe edit")
    extra = (
        marker
        + f"      - {overlay}/node/panel_client.py:/app/app/panel_client.py:ro\n"
        + f"      - {overlay}/node/core_adapters.py:/app/app/core_adapters.py:ro\n"
    )
    s = s.replace(marker, extra, 1)
    path.write_text(s)
print("Node compose mounts: OK")
PY
    fi

    if [ -f "$SMITE_PANEL_COMPOSE" ]; then
        docker compose -f "$SMITE_PANEL_COMPOSE" config >/dev/null || {
            echo "ERROR: Panel compose validation failed. Restore the generated .bak file before continuing."
            return 1
        }
    fi

    if [ -f "$SMITE_NODE_COMPOSE" ]; then
        docker compose -f "$SMITE_NODE_COMPOSE" config >/dev/null || {
            echo "ERROR: Node compose validation failed. Restore the generated .bak file before continuing."
            return 1
        }
    fi

    echo "Smite compose files validated successfully."
}

smite_prepare_persistent_compatibility() {
    clear
    echo "======================================"
    echo "    Prepare Smite 443 Compatibility"
    echo "======================================"
    echo
    echo "This prepares persistent bind-mounted compatibility files."
    echo "It does NOT recreate containers yet."
    echo

    smite_require_docker || {
        read -rp "Press Enter to return..."
        return
    }

    if ! smite_container_exists smite-panel && ! smite_container_exists smite-node; then
        echo "ERROR: No Smite panel or node container was detected."
        echo
        read -rp "Press Enter to return..."
        return
    fi

    if ! smite_prepare_overlays; then
        echo
        echo "Preparation failed. No compose activation was performed."
        read -rp "Press Enter to return..."
        return
    fi

    if ! smite_patch_compose_mounts; then
        echo
        echo "Compose preparation failed. Containers were not recreated."
        read -rp "Press Enter to return..."
        return
    fi

    echo
    echo "Preparation completed."
    echo "Use Activate Smite 443 Compatibility to recreate only detected Smite services."
    echo
    read -rp "Press Enter to return..."
}

smite_activate_persistent_compatibility() {
    clear
    echo "======================================"
    echo "    Activate Smite 443 Compatibility"
    echo "======================================"
    echo

    smite_require_docker || {
        read -rp "Press Enter to return..."
        return
    }

    read -rp "Recreate detected Smite services with persistent overlays? [y/N]: " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *)
            echo "Activation cancelled."
            sleep 1
            return
            ;;
    esac

    if smite_container_exists smite-panel && [ -f "$SMITE_PANEL_COMPOSE" ]; then
        echo "Recreating smite-panel..."
        docker compose -f "$SMITE_PANEL_COMPOSE" up -d --force-recreate smite-panel || {
            echo "ERROR: Failed to recreate smite-panel."
            read -rp "Press Enter to return..."
            return
        }
        if ! smite_wait_healthy smite-panel 90; then
            echo "ERROR: smite-panel did not become healthy."
            read -rp "Press Enter to return..."
            return
        fi
    fi

    if smite_container_exists smite-node && [ -f "$SMITE_NODE_COMPOSE" ]; then
        echo "Recreating smite-node..."
        docker compose -f "$SMITE_NODE_COMPOSE" up -d --force-recreate smite-node || {
            echo "ERROR: Failed to recreate smite-node."
            read -rp "Press Enter to return..."
            return
        }
        if ! smite_wait_healthy smite-node 90; then
            echo "ERROR: smite-node did not become healthy."
            read -rp "Press Enter to return..."
            return
        fi
    fi

    echo
    echo "Smite compatibility overlays are active."
    echo "Recommended next checks: panel status, node status, tunnel restore, and client connectivity."
    echo
    read -rp "Press Enter to return..."
}

show_smite_menu() {
    while true; do
        clear
        echo "======================================"
        echo "        Smite Management"
        echo "======================================"
        echo
        echo "1) Smite 443 Status"
        echo "2) Prepare Persistent 443 Compatibility"
        echo "3) Activate Persistent 443 Compatibility"
        echo
        echo "0) Back"
        echo

        read -rp "Please enter your selection [0-3]: " smite_choice
        case "$smite_choice" in
            1) smite_show_status ;;
            2) smite_prepare_persistent_compatibility ;;
            3) smite_activate_persistent_compatibility ;;
            0) break ;;
            *)
                echo
                echo "Invalid selection!"
                sleep 2
                ;;
        esac
    done
}
