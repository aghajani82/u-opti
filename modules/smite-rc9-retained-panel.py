#!/usr/bin/env python3
"""Upgrade or recover only the Panel in an existing signed RC9 installation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
SOURCE = "159174eb523a91e82292effd4930341b9b72e384"
IMAGE = ("ghcr.io/aghajani82/smite-panel@sha256:"
         "02538fece887a82fd49815514722aceb472d18956d05f49e5561d3ebdc206567")
STATE = Path("/var/lib/u-opti/smite-rc9-retained-panel")
OVERLAY_NAME = "docker-compose.retained-panel-rc9.yml"
BUNDLE = HERE / "smite-rc9-retained-panel-approved.sigstore.json"
APPROVAL_COMMIT = "91f32aa21ef0ebd1da421b746278371941fd9cb5"
BUNDLE_SHA256 = "8196469ff6aa059e831732f0e4befdd6af9d5e73538934215e67b227c0963e8f"
BRANCH = "refs/heads/trial/unified-smite-install"
ISSUER = "https://token.actions.githubusercontent.com"


def overlay(rt):
    return rt.p.PANEL / OVERLAY_NAME


def overlay_bytes():
    return f"services:\n  smite-panel:\n    image: {IMAGE}\n".encode()


def release_bytes():
    return (json.dumps({
        "activation_allowed": True, "image": IMAGE, "scope": "retained_rc9_iran_panel_only",
        "schema": 1, "source_sha": SOURCE,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode()


def verify_signed_image(rt, cosign, trusted_root):
    rt.run([cosign, "verify", "--trusted-root", str(trusted_root),
            "--certificate-oidc-issuer=" + ISSUER,
            "--certificate-identity=https://github.com/aghajani82/Smite/.github/workflows/"
            "unified-install-signed-trial.yml@" + BRANCH,
            "--certificate-github-workflow-repository=aghajani82/Smite",
            "--certificate-github-workflow-trigger=push",
            "--certificate-github-workflow-sha=" + SOURCE,
            "-a", "smite_role=panel", "-a", "smite_source_sha=" + SOURCE,
            "-a", "smite_trial=unified-install", IMAGE])


@contextmanager
def cosign_binary(rt, digest):
    binary = shutil.which("cosign")
    if binary:
        yield binary
        return

    parent = STATE.parent
    rt.trusted_path(parent, directory=True)
    helper = HERE / "smite-install.sh"
    rt.trusted_path(helper)
    rt.need(os.uname().machine == "x86_64", "RC9_COSIGN_UNSUPPORTED_ARCHITECTURE")
    with tempfile.TemporaryDirectory(prefix="smite-panel-cosign-", dir=parent) as work:
        target = Path(work) / "cosign"
        env = {key: value for key, value in os.environ.items() if key != "BASH_ENV"}
        try:
            result = subprocess.run(
                ["/bin/bash", "--noprofile", "--norc", "-c",
                 'source "$1" && smite_install_rc7_verified_cosign "$2" "$3"',
                 "retained-panel-cosign", str(helper), str(target), digest],
                env=env, timeout=900, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise rt.Hold("RC9_COSIGN_BOOTSTRAP_FAILED") from exc
        rt.need(result.returncode == 0, "RC9_COSIGN_BOOTSTRAP_FAILED")
        rt.trusted_path(target)
        target.chmod(0o700)
        yield str(target)


def verify_release(rt, binary, digest, root):
    rt.trusted_path(Path(binary))
    with open(binary, "rb") as stream:
        rt.need(hashlib.file_digest(stream, "sha256").hexdigest() == digest,
                "RC9_COSIGN_DIGEST_MISMATCH")
    rt.run([binary, "verify-blob", "--trusted-root", str(root), "--bundle", str(BUNDLE),
            "--certificate-oidc-issuer=" + ISSUER,
            "--certificate-identity=https://github.com/aghajani82/u-opti/.github/workflows/"
            "smite-unified-trial-signed-pair-review.yml@" + BRANCH,
            "--certificate-github-workflow-repository=aghajani82/u-opti",
            "--certificate-github-workflow-trigger=push",
            "--certificate-github-workflow-sha=" + APPROVAL_COMMIT, "-"],
           input=release_bytes().decode())
    verify_signed_image(rt, binary, root)


def signed_release(rt):
    rt.need(re.fullmatch("[a-f0-9]{40}", APPROVAL_COMMIT) and BUNDLE.is_file(),
            "RETAINED_PANEL_SIGNED_APPROVAL_REQUIRED")
    root = HERE / "smite-rc7-sigstore-trusted-root.json"
    rt.trusted_path(root)
    verifier = rt.load("smite-registry-pair-admission.py")
    verifier._validated_trusted_root(root)
    rt.trusted_path(BUNDLE)
    rt.need(hashlib.sha256(BUNDLE.read_bytes()).hexdigest() == BUNDLE_SHA256,
            "RETAINED_PANEL_APPROVAL_BUNDLE_CHANGED")
    digest = verifier.COSIGN_RC7_AMD64_SHA256
    with cosign_binary(rt, digest) as binary:
        verify_release(rt, binary, digest, root)


def read_record(rt):
    path = STATE / "record.json"
    rt.need(stat.S_IMODE(rt.trusted_path(STATE, directory=True).st_mode) == 0o700
            and stat.S_IMODE(rt.trusted_path(path).st_mode) == 0o600
            and path.stat().st_size <= 4096, "RETAINED_PANEL_JOURNAL_UNSAFE")
    rec = json.loads(path.read_text())
    rt.need(set(rec) == {"phase", "image_id", "wss_sha", "services"}
            and rec["phase"] in {"PREPARED", "COMMITTED", "ROLLING_BACK", "ROLLED_BACK"}
            and re.fullmatch("sha256:[a-f0-9]{64}", rec["image_id"]),
            "RETAINED_PANEL_JOURNAL_INVALID")
    return rec


def wss_sha(rt):
    path = rt.STATE / "record.json"
    rt.trusted_path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(rt, ingress, rec, *, create=False):
    ingress.replace_bytes(rt, STATE / "record.json",
                          (json.dumps(rec, sort_keys=True) + "\n").encode(), 0o600,
                          create=create)


def check_overlay(rt):
    path = overlay(rt)
    rt.trusted_path(path)
    rt.need(path.read_bytes() == overlay_bytes(), "RETAINED_PANEL_OVERLAY_DRIFT")


def original_identity(rt, obj, doc, old_image):
    """Compare the rest of the runtime directly to the original receipt."""
    if obj["Config"].get("Image") != IMAGE:
        return
    rt.need(doc["state"] == "COMMITTED" and doc["role"] == "ir",
            "RETAINED_PANEL_WSS_SCOPE_CHANGED")
    record = read_record(rt)
    rt.need(record["phase"] in {"PREPARED", "COMMITTED"} and record["wss_sha"] == wss_sha(rt)
            and obj["Image"] == record["image_id"]
            and obj["Image"] == rt.run(["docker", "image", "inspect", "-f", "{{.Id}}", IMAGE]),
            "RETAINED_PANEL_IMAGE_DRIFT")
    check_overlay(rt)
    config = obj["Config"]
    labels = config["Labels"]
    files = [*doc["baseline"]["smite-panel"]["files"], str(overlay(rt)),
             str(rt.overlay_path("smite-panel"))]
    key = "com.docker.compose.project.config_files"
    rt.need(labels.get(key) == ",".join(files), "RETAINED_PANEL_COMPOSE_OWNER_DRIFT")
    labels[key] = ",".join([*files[:-2], files[-1]])
    config["Image"] = old_image
    obj["Image"] = doc["baseline"]["smite-panel"]["image_id"]


def compose_commands(rt, doc, *, installed):
    name = "smite-panel"
    rt.trusted_path(rt.overlay_path(name))
    rt.check_rc9_compose(name, doc)
    old = rt.compose(name, doc, True)
    if installed:
        check_overlay(rt)
        new = [*old[:-2], "-f", str(overlay(rt)), *old[-2:]]
        command = new
        source = None
    else:
        command = [*old[:-2], "-f", "-", *old[-2:]]
        source = overlay_bytes().decode()
        new = None
    flags = ["config", "--format", "json"]
    before = json.loads(rt.run(old + flags))
    after = json.loads(rt.run(command + flags, input=source))
    before["services"][name]["image"] = IMAGE
    rt.need(before == after, "RETAINED_PANEL_COMPOSE_CHANGE_EXCEEDS_IMAGE")
    return old, new


def continuity(rt, route):
    node = rt.inspect_container("smite-node")
    tracked = []
    processes = rt.run(["docker", "top", "smite-node", "-eo", "pid,comm"])
    for row in processes.splitlines()[1:]:
        pid, command = row.split(maxsplit=1)
        if command in ("frps", "backhaul"):
            ticks = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
            tracked.append([int(pid), ticks, command])
    owner, ports = route._frps_socket_inventory()
    rt.need(any(item[0] == owner and item[2] == "frps" for item in tracked),
            "RETAINED_PANEL_EXPECTED_TUNNELS_NOT_RUNNING")
    return [node["Id"], node["State"]["StartedAt"], sorted(tracked), sorted(ports)]


def backup_database(rt):
    path = rt.p.PANEL / "panel/data/smite.db"
    rt.trusted_path(path)
    target = STATE / "panel-before.sqlite3"
    rt.atomic_new(target, b"")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10) as original:
        with sqlite3.connect(target) as backup:
            original.backup(backup, sleep=0.1)
            rt.need(backup.execute("PRAGMA integrity_check").fetchone() == ("ok",),
                    "RETAINED_PANEL_BACKUP_INVALID")
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    rt.fsync_dir(STATE)


def recreate(rt, command):
    rt.run([*command, "up", "-d", "--no-deps", "--no-build", "--pull", "never",
            "--force-recreate", "smite-panel"], timeout=180)


def check_published_routes(rt, ingress, worker, route, domain):
    route._safe_directory(route.ROUTE_DIR)
    found = False
    for path in sorted(route.ROUTE_DIR.glob(".*.transaction.json")):
        rec = json.loads(ingress.read_trusted(rt, path, 0o600))
        if rec.get("kind") != "backhaul" or rec.get("state") != "COMMITTED":
            continue
        port, xhttp = rec["port"], rec["path"]
        worker.validate_port(port, ingress.CONTROL_RESERVED_PORTS)
        rt.need(path.name == f".{port}.transaction.json" and isinstance(xhttp, str)
                and worker.XHTTP_PATH.fullmatch(xhttp), "RETAINED_PANEL_ROUTE_JOURNAL_INVALID")
        config = route.ROUTE_DIR / f"{port}.conf"
        rt.need(ingress.read_trusted(rt, config, 0o644).decode() == rec["snippet"]
                and worker.probe(rt, domain, port, xhttp, public=True),
                "RETAINED_PANEL_ROUTE_UNVERIFIED")
        found = True
    return found


def verified_continuity(rt, ingress, worker, route, domain):
    published = check_published_routes(rt, ingress, worker, route, domain)
    live = continuity(rt, route)
    rt.need(published == any(item[2] == "backhaul" for item in live[2]),
            "RETAINED_PANEL_BACKHAUL_RUNTIME_MISMATCH")
    return live


def prove_health(edge, ingress, worker, *, candidate):
    rt = edge.rt
    for attempt in range(30):
        try:
            ingress.run_operation(edge, "ir", "verify")
            if candidate:
                worker.queue(rt, "check")
            return
        except (rt.Hold, RuntimeError):
            if attempt == 29:
                raise
            time.sleep(2)


def recover(edge, ingress, worker, route, doc, rec):
    rt = edge.rt
    rt.need(rec["wss_sha"] == wss_sha(rt), "RETAINED_PANEL_WSS_JOURNAL_CHANGED")
    rt.check_protected(doc)
    rt.ensure_service("smite-node", doc, enabled=True)
    live = continuity(rt, route)
    if os.path.lexists(overlay(rt)):
        check_overlay(rt)
    old, _ = compose_commands(rt, doc, installed=os.path.lexists(overlay(rt)))
    panel_id = rt.run(["docker", "ps", "-aq", "--filter", "name=^/smite-panel$"])
    old_healthy = False
    if panel_id:
        panel = rt.inspect_container("smite-panel")
        labels = panel["Config"]["Labels"]
        files = doc["baseline"]["smite-panel"]["files"]
        old_files = [*files, str(rt.overlay_path("smite-panel"))]
        new_files = [*files, str(overlay(rt)), old_files[-1]]
        old_image = rt.load("smite-managed-frp-control.py").RC9_PANEL_IMAGE
        allowed = {old_image: (old_files, doc["baseline"]["smite-panel"]["image_id"]),
                   IMAGE: (new_files, rec["image_id"])}
        actual = panel["Config"]["Image"]
        rt.need(actual in allowed and labels.get("com.docker.compose.project") == doc["project"]
                and labels.get("com.docker.compose.service") == "smite-panel",
                "RETAINED_PANEL_RECOVERY_OWNER_CHANGED")
        paths, image_id = allowed[actual]
        rt.need(labels.get("com.docker.compose.project.config_files") == ",".join(paths)
                and panel["Image"] == image_id, "RETAINED_PANEL_RECOVERY_OWNER_CHANGED")
        if actual == old_image and panel["State"].get("Health", {}).get("Status") == "healthy":
            rt.ensure_service("smite-panel", doc, enabled=True)
            old_healthy = True
    worker.disable_panel_queue(ingress, rt)
    rec["phase"] = "ROLLING_BACK"
    save(rt, ingress, rec)
    if not old_healthy:
        recreate(rt, old)
    prove_health(edge, ingress, worker, candidate=False)
    rt.need(verified_continuity(rt, ingress, worker, route, doc["domain"]) == live,
            "RETAINED_PANEL_TUNNEL_CONTINUITY_CHANGED")
    overlay(rt).unlink(missing_ok=True)
    rt.fsync_dir(overlay(rt).parent)
    rec["phase"] = "ROLLED_BACK"
    save(rt, ingress, rec)


def apply(edge, ingress, worker, route, doc):
    rt = edge.rt
    if os.path.lexists(STATE):
        rec = read_record(rt)
        if rec["phase"] == "COMMITTED":
            prove_health(edge, ingress, worker, candidate=True)
            verified_continuity(rt, ingress, worker, route, doc["domain"])
            worker.enable_panel_queue(edge, ingress)
            return
        rt.need(rec["phase"] == "ROLLED_BACK", "RETAINED_PANEL_RECOVER_REQUIRED")
    else:
        rec = None
    ingress.run_operation(edge, "ir", "verify")
    rt.need(not os.path.lexists(overlay(rt)), "RETAINED_PANEL_BASELINE_CHANGED")
    compose_commands(rt, doc, installed=False)
    signed_release(rt)
    rt.run(["docker", "pull", IMAGE], timeout=300)
    revision = rt.run(["docker", "image", "inspect", "-f",
                       '{{index .Config.Labels "org.opencontainers.image.revision"}}', IMAGE])
    rt.need(revision == SOURCE, "RETAINED_PANEL_IMAGE_REVISION_CHANGED")
    image_id = rt.run(["docker", "image", "inspect", "-f", "{{.Id}}", IMAGE])
    rt.need(re.fullmatch("sha256:[a-f0-9]{64}", image_id), "RETAINED_PANEL_IMAGE_ID_INVALID")
    live = verified_continuity(rt, ingress, worker, route, doc["domain"])
    if rec is not None:
        rt.archive_restored_journal(STATE)
    STATE.mkdir(mode=0o700)
    rt.fsync_dir(STATE.parent)
    rec = {"phase": "PREPARED", "image_id": image_id, "wss_sha": wss_sha(rt),
           "services": live}
    save(rt, ingress, rec, create=True)
    try:
        backup_database(rt)
        rt.atomic_new(overlay(rt), overlay_bytes(), 0o644)
        _, candidate = compose_commands(rt, doc, installed=True)
        recreate(rt, candidate)
        prove_health(edge, ingress, worker, candidate=True)
        rt.need(verified_continuity(rt, ingress, worker, route, doc["domain"]) == rec["services"],
                "RETAINED_PANEL_TUNNEL_CONTINUITY_CHANGED")
        rec["phase"] = "COMMITTED"
        save(rt, ingress, rec)
        worker.enable_panel_queue(edge, ingress)
    except Exception as exc:
        try:
            recover(edge, ingress, worker, route, doc, rec)
        except Exception as recovery:
            raise rt.Hold("RETAINED_PANEL_RECOVER_REQUIRED") from recovery
        raise rt.Hold("RETAINED_PANEL_APPLY_FAILED_RESTORED") from exc


def confirm(rt, action):
    challenge = action.upper() + "-RC9-PANEL-ONLY"
    rt.need(sys.stdin.isatty() and input(f"Type {challenge}: ").strip() == challenge,
            "OPERATOR_CANCELLED")


def setup(edge, ingress, worker, route, doc):
    rt = edge.rt
    if os.path.lexists(STATE) and read_record(rt)["phase"] == "COMMITTED":
        ingress.run_operation(edge, "ir", "verify")
        worker.queue(rt, "check")
        verified_continuity(rt, ingress, worker, route, doc["domain"])
        timer, paths = worker.panel_queue_units(ingress, rt)
        if all(path.is_file() for path in paths):
            try:
                rt.run(["systemctl", "is-enabled", "--quiet", timer], timeout=10)
                rt.run(["systemctl", "is-active", "--quiet", timer], timeout=10)
            except rt.Hold:
                pass
            else:
                return "ALREADY_READY"
        print("Enable Backhaul publishing in the installed Panel.")
    else:
        print("Upgrade the Iran Panel and enable Backhaul publishing. The Panel restarts briefly.")
    confirm(rt, "apply")
    apply(edge, ingress, worker, route, doc)
    return "APPLIED"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "rollback", "setup"))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("retained_panel_worker", HERE / "smite-rc9-backhaul-xhttp.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    edge = worker.load("retained_panel_edge", "smite-rc7-wss-edge.py")
    ingress = worker.load("retained_panel_ingress", "smite-rc9-backhaul-ingress.py")
    route = worker.load("retained_panel_route", "smite-xhttp-nginx-route", executable=True)
    edge.select_rc9()
    rt = edge.rt
    try:
        rt.need(os.geteuid() == 0, "ROOT_REQUIRED")
        if args.action in ("apply", "rollback"):
            confirm(rt, args.action)
        with rt.locked(), worker.route_lock(route):
            doc = rt.record()
            rt.need(doc["role"] == "ir" and doc["state"] == "COMMITTED",
                    "RETAINED_PANEL_REQUIRES_COMMITTED_IR_RC9")
            if args.action == "setup":
                rt.load("smite-stage15-xhttp-bridge.py").verify()
                outcome = setup(edge, ingress, worker, route, doc)
            elif args.action == "apply":
                apply(edge, ingress, worker, route, doc)
                outcome = "APPLIED"
            elif args.action == "rollback":
                rec = read_record(rt)
                if rec["phase"] != "ROLLED_BACK":
                    recover(edge, ingress, worker, route, doc, rec)
                outcome = "ROLLED_BACK"
            else:
                ingress.run_operation(edge, "ir", "verify")
                verified_continuity(rt, ingress, worker, route, doc["domain"])
                compose_commands(rt, doc, installed=os.path.lexists(overlay(rt)))
                signed_release(rt)
                outcome = "READY"
        print("RETAINED_RC9_PANEL=" + outcome)
        return 0
    except Exception as exc:
        reason = str(exc)
        print("HOLD: " + (reason if re.fullmatch("[A-Z0-9_]{1,100}", reason)
                          else "RETAINED_PANEL_OPERATION_UNVERIFIED"), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
