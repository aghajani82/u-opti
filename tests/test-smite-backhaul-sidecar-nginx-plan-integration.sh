#!/usr/bin/env bash
# Real Nginx syntax validation in disposable Docker containers only.
# No host ports, host services, domain lookups, SSH, or live IR/KH access.
set -Eeuo pipefail
cd "$(dirname "$0")/.."

ROOT="$(mktemp -d -t uopti-nginx-plan-ci-XXXXXXXX)"
trap 'rm -rf -- "$ROOT"' EXIT
chmod 700 "$ROOT"

# Generate an isolated, disposable TLS key; NEVER print it or ship it.
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=ir.example.com' \
  -keyout "$ROOT/tls.key" -out "$ROOT/tls.crt" >/dev/null 2>&1
chmod 600 "$ROOT/tls.key" "$ROOT/tls.crt"

cat > "$ROOT/nginx.conf" <<'CONF'
worker_processes 1;
pid /tmp/nginx.pid;
events { worker_connections 128; }
http {
    access_log off;
    include /etc/nginx/conf.d/*.conf;
}
CONF

mkdir -p "$ROOT/conf.d"
python3 -B - "$ROOT" <<'PY'
from pathlib import Path
import importlib.util
import sys

base = Path(sys.argv[1])
f = Path("modules/smite-backhaul-sidecar-nginx-plan.py").resolve()
spec = importlib.util.spec_from_file_location("sidecar_plan_ci", f)
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)

ir = b"""server {
    listen 127.0.0.1:8443 ssl;
    server_name ir.example.com;
    ssl_certificate /etc/nginx/tls.crt;
    ssl_certificate_key /etc/nginx/tls.key;
    location = /~!frp {
        proxy_pass http://127.0.0.1:7000;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}
"""
kh = b"""server {
    listen 443 ssl;
    server_name kh.example.com;
    ssl_certificate /etc/nginx/tls.crt;
    ssl_certificate_key /etc/nginx/tls.key;
    location / { return 404; }
    location ~ ^/(?<fwdport>[0-9]+)/(?<fwdpath>.*)$ {
        proxy_pass http://127.0.0.1:$fwdport$is_args$args;
    }
}
"""
for role, content in (("ir", ir), ("kh", kh)):
    changed, includes, _ = plan.compile_nginx(
        role, content, "ir.example.com", "kh.example.com")
    directory = base / role
    directory.mkdir(mode=0o700)
    (directory / "main.conf").write_bytes(changed)
    for target, data in includes.items():
        # exact target is /etc/nginx/*.inc or /etc/nginx/conf.d/*.conf
        relative = Path(target).relative_to("/etc/nginx")
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (directory / "nginx.conf").write_text((base / "nginx.conf").read_text())
    (directory / "tls.key").write_bytes((base / "tls.key").read_bytes())
    (directory / "tls.crt").write_bytes((base / "tls.crt").read_bytes())
    dest = directory / "conf.d" / "main.conf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(changed)
    (directory / "main.conf").unlink()
PY

for role in ir kh; do
    echo "Nginx integrated role: $role"
    # Nginx runner is isolated and does not bind any host TCP sockets.
    docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges \
        --tmpfs /tmp:rw,noexec,nosuid,size=8m \
        --mount "type=bind,src=$ROOT/$role,dst=/etc/nginx,readonly" \
        nginx:stable-alpine nginx -t -c /etc/nginx/nginx.conf

    # Invalid directive must be rejected by the real Nginx parser.
    printf '\nnot_a_real_nginx_directive yes;\n' >> "$ROOT/$role/nginx.conf"
    if docker run --rm --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges \
        --tmpfs /tmp:rw,noexec,nosuid,size=8m \
        --mount "type=bind,src=$ROOT/$role,dst=/etc/nginx,readonly" \
        nginx:stable-alpine nginx -t -c /etc/nginx/nginx.conf >/dev/null 2>&1; then
        echo "ERROR: Nginx accepted deliberate invalid directive ($role)" >&2
        exit 1
    fi
done
echo "PASS: Both candidate Nginx layouts validated in disposable Docker"
