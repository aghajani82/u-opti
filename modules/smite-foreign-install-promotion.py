"""Trial-only, offline-safe Foreign Gateway admission and identity promotion.

This is not a host installer and never starts/recreates Node, alters Gateway,
Nginx, Sanaei, FRP, replay, or Compose. An already redeemed staged secret must
pass a fresh signed Panel proof before a no-overwrite runtime identity write.
Both a PREPARED and COMPLETED journal are retained for crash recovery.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import urlsplit


class Hold(ValueError):
    """Fail closed without exposing secrets or paths from untrusted inputs."""


def deny():
    raise Hold("Foreign installation promotion unavailable; retain staged identity")


@contextmanager
def private_directory(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        deny()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            deny()
        yield fd
    finally:
        os.close(fd)


def read_optional(fd, name, client, limit=8192):
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return None
    try:
        client.private_file(descriptor)
        raw = os.read(descriptor, limit + 1)
        if len(raw) > limit:
            deny()
        return raw
    finally:
        os.close(descriptor)


def write_once(fd, name, data):
    if not isinstance(data, bytes) or len(data) > 8192:
        deny()
    temporary = ".promote-" + secrets.token_hex(16)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd,
                follow_symlinks=False)
        os.fsync(fd)
    finally:
        os.unlink(temporary, dir_fd=fd)


def decode_record(raw, client):
    if raw is None:
        return None
    return client.decode(raw)


def read_env(path):
    """Read only existing private host-side managed state; no shell evaluation."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        deny()
    # Managed Node directory may be 0755; its state file stays private 0600.
    # Verify every ancestor without enforcing identity-directory mode on Node.
    parent = path.parent
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in parent.parts[1:]:
            nxt = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=directory)
            os.close(directory)
            directory = nxt
        info = os.fstat(directory)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            deny()
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                deny()
            raw = os.read(fd, 65537)
            if len(raw) > 65536:
                deny()
        finally:
            os.close(fd)
    finally:
        os.close(directory)
    try:
        lines = raw.decode("utf-8").splitlines()
        values = {}
        for line in lines:
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition("=")
            if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
                deny()
            values[key] = val
        return values
    except (UnicodeDecodeError, ValueError):
        deny()


def verify_gateway(packet, *, state_path, gateway_path, node_env_path, client):
    """Bind the staged Panel/Foreign scope to the existing paused host config."""
    scope = packet.scope
    state = read_env(state_path)
    gateway = read_env(gateway_path)
    env = read_env(node_env_path)
    panel_host = urlsplit(scope["panel_url"]).hostname
    foreign_host = urlsplit(scope["origin"]).hostname
    path = urlsplit(scope["control_url"]).path
    if (state.get("SMITE_ROLE") != "foreign"
            or state.get("SMITE_CONNECTION_MODE") != "standard"
            or state.get("SMITE_NODE_NAME") != scope["node_name"]
            or state.get("SMITE_PANEL_DOMAIN") != panel_host
            or gateway.get("SMITE_FOREIGN_GATEWAY_DOMAIN") != foreign_host
            or gateway.get("SMITE_FOREIGN_PANEL_DOMAIN") != panel_host
            or gateway.get("SMITE_FOREIGN_CONTROL_PATH") != path
            or gateway.get("SMITE_FOREIGN_GATEWAY_PUBLIC_PORT") != "443"
            or gateway.get("SMITE_FOREIGN_GATEWAY_MODE") != "https-control-path"
            or env.get("PANEL_ADDRESS") != panel_host + ":443"
            or env.get("SMITE_NODE_PANEL_AUTH_MODE") != "paused"
            or env.get("SMITE_AGENT_AUTH_MODE") != "strict"
            or env.get("SMITE_ENGINE_INVENTORY_MODE") != "managed"):
        deny()
    control = env.get("SMITE_CONTROL_ADDRESS", "")
    try:
        parsed = urlsplit(control)
        if (parsed.scheme != "https" or parsed.hostname != foreign_host
                or parsed.port not in (None, 443) or parsed.path != path
                or parsed.query or parsed.fragment or parsed.username or parsed.password
                or control not in (f"https://{foreign_host}{path}",
                                   f"https://{foreign_host}:443{path}")):
            deny()
    except ValueError:
        deny()
    return True


def promote(raw, *, client, directory, live_identity, state_path, gateway_path,
            node_env_path, transport=None, now=None):
    """Prove enrolled identity, admit exact Gateway and promote without overwrite.

    Caller creates a root-owned 0700 staging directory and a separate, existing
    0700 runtime identity directory. No activation occurs. Retry this function
    after any lost response, including after code expiry.
    """
    packet = client.parse_packet(raw)
    transport = client.post if transport is None else transport
    live = Path(live_identity)
    if (live.name != "node-identity.json" or not live.is_absolute()
            or ".." in live.parts or Path(directory) == live.parent):
        deny()
    try:
        with client.locked_directory(directory) as staged:
            saved = decode_record(read_optional(staged, "foreign-install-identity.json", client),
                                  client)
            if (not isinstance(saved, dict)
                    or set(saved) != {"schema", "scope", "node_secret"}
                    or saved["schema"] != 1 or saved["scope"] != packet.scope
                    or not isinstance(saved["node_secret"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", saved["node_secret"])):
                deny()
            verify_gateway(packet, state_path=state_path, gateway_path=gateway_path,
                           node_env_path=node_env_path, client=client)
            body = json.dumps({"node_id": packet.scope["node_id"]},
                              separators=(",", ":")).encode()
            moment = int(client.time.time()) if now is None else now
            proof = transport(packet.scope["panel_url"], client.STATUS, body,
                              client.signed_headers(packet.scope, saved["node_secret"], body, moment))
            expected = {"status": "enrolled", **{
                k: v for k, v in packet.scope.items() if k != "panel_url"}}
            if proof != expected:
                deny()
            payload = json.dumps({"version": 1, "node_id": packet.scope["node_id"],
                                  "node_secret": saved["node_secret"]},
                                 sort_keys=True, separators=(",", ":")).encode("ascii")
            receipt = {"schema": 1, "scope": packet.scope,
                       "destination": str(live),
                       "sha256": hashlib.sha256(payload).hexdigest()}
            done = dict(receipt, status="completed")
            with private_directory(live.parent) as destination:
                old = read_optional(destination, live.name, client, 4096)
                prepared = decode_record(read_optional(staged,
                                        "foreign-install-promotion-prepared.json", client), client)
                completed = decode_record(read_optional(staged,
                                         "foreign-install-promotion-completed.json", client), client)
                if (prepared is not None and prepared != receipt
                        or completed is not None and completed != done
                        or completed is not None and prepared != receipt):
                    deny()
                if prepared is None:
                    if old is not None:
                        deny()
                    write_once(staged, "foreign-install-promotion-prepared.json",
                               json.dumps(receipt, sort_keys=True).encode())
                if old is None:
                    if completed is not None or read_optional(destination,
                                               "replay-enrollment.json", client) is not None:
                        deny()
                    write_once(destination, live.name, payload)
                elif old != payload:
                    deny()
                if completed is None:
                    write_once(staged, "foreign-install-promotion-completed.json",
                               json.dumps(done, sort_keys=True).encode())
            return {"status": "identity_promoted", "node_id": packet.scope["node_id"],
                    "runtime_activation": "not_performed"}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        deny()
