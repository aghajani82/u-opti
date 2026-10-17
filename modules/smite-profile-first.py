#!/usr/bin/env python3
"""Non-secret dual XHTTP profile plan, usable BEFORE Smite is installed.

This plans only; it NEVER creates Xray inbounds, FRP tunnels, Backhaul tokens,
Nginx routes, Docker containers or systemd services. Port/Path must later be
verified against the independently created KH Sanaei inbounds.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
DEFAULT_PLAN = Path("/etc/u-opti/tunnels/profile-first.json")


class ProfileHold(ValueError):
    pass


def load_helper(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise ProfileHold("Required profile validator missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate(fp: object, fx: object, bp: object, bx: object) -> dict:
    frp = load_helper("smite-frp-xhttp-paths.py", "profile_first_frp")
    backhaul = load_helper("smite-backhaul-sidecar.py", "profile_first_bh")
    try:
        fport = frp.valid_port(fp)
        fpath = frp.valid_path(fx, fport)
        bport, bpath = backhaul.validated_profile(int(bp), bx)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProfileHold("Invalid FRP or Backhaul port / XHTTP Path") from exc
    if not isinstance(bp, (int, str)) or isinstance(bp, bool) or not str(bp).isascii() or not str(bp).isdecimal():
        raise ProfileHold("Invalid Backhaul port")
    if str(fport) != str(fp) or str(bport) != str(bp) or fport == bport:
        raise ProfileHold("FRP and Backhaul must use distinct canonical ports")
    if bport in (56053,) and fport == bport:
        raise ProfileHold("Duplicate data ports")
    numeric = bpath.split("/")[1]
    if numeric in {"api", "assets", "auth", "channel", "docs", "login", "static", "sub", "tunnel", "openapi.json"}:
        raise ProfileHold("Backhaul Path overlaps a reserved gateway namespace")
    if numeric.isdecimal() and int(numeric) != bport:
        raise ProfileHold("Backhaul numeric Path prefix must equal Backhaul port")
    if frp.overlaps(fpath, bpath):
        raise ProfileHold("FRP and Backhaul XHTTP Paths overlap")
    return {"version": 1, "frp": {"port": fport, "path": fpath},
            "backhaul": {"port": bport, "path": bpath}}


def safe_dir(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or (
            stat.S_IMODE(info.st_mode) & 0o022):
        raise ProfileHold("Unsafe profile directory")


def safe_file(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 2048):
        raise ProfileHold("Unsafe profile file")


def load(path: Path) -> dict | None:
    if path.is_symlink():
        raise ProfileHold("Profile must never be a symlink")
    if not path.exists():
        return None
    safe_dir(path.parent)
    safe_file(path)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or set(obj) != {"version", "frp", "backhaul"} or obj["version"] != 1:
            raise ValueError()
        f, b = obj["frp"], obj["backhaul"]
        if not isinstance(f, dict) or not isinstance(b, dict) or set(f) != {"port", "path"} or set(b) != {"port", "path"}:
            raise ValueError()
        if not isinstance(f["port"], int) or not isinstance(b["port"], int):
            raise ValueError()
        validated = validate(f["port"], f["path"], b["port"], b["path"])
        if validated != obj:
            raise ValueError()
        return validated
    except (ValueError, TypeError, UnicodeError, OSError) as exc:
        raise ProfileHold("Invalid profile content; manual review required") from exc


FRP_NGINX_ROUTES = Path("/etc/nginx/u-opti-smite-frp-xhttp.conf")


def active_traces() -> bool:
    # Never replace a plan once a Sidecar, explicit FRP registry or
    # auto-published FRP Nginx route is active. Missing registry does not
    # imply inactive FRP once the Profile First fallback is supported.
    if any(os.path.lexists(str(p)) for p in (
        Path("/var/lib/u-opti/backhaul-trial/ir"),
        Path("/var/lib/u-opti/backhaul-trial/kh"),
        Path("/etc/u-opti/backhaul-sidecar/ir.toml"),
        Path("/etc/u-opti/backhaul-sidecar/kh.toml"),
        Path("/etc/u-opti/smite/frp-xhttp-paths.json"),
    )):
        return True
    try:
        if not FRP_NGINX_ROUTES.exists() and not FRP_NGINX_ROUTES.is_symlink():
            return False
        st = FRP_NGINX_ROUTES.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > 65536:
            return True
        routes = FRP_NGINX_ROUTES.read_text(encoding="utf-8")
        return bool(re.search(r"(?m)^\s*location\s+(?:=|\^~)\s+/", routes))
    except (OSError, UnicodeError):
        return True


def store(path: Path, obj: dict, replace: bool = False) -> str:
    if os.geteuid() != 0:
        raise ProfileHold("Root required to save plan")
    if path.parent.name != "tunnels" or path.name != "profile-first.json":
        raise ProfileHold("Untrusted plan destination")
    base = path.parent.parent
    if not base.exists():
        base.mkdir(mode=0o755)
    safe_dir(base)
    if not path.parent.exists():
        path.parent.mkdir(mode=0o700)
    safe_dir(path.parent)
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise ProfileHold("Private plan directory must have mode 0700")
    before = load(path)
    if before == obj:
        return "PROFILE_FIRST_ALREADY_MATCHED_NO_CHANGE"
    if before is not None:
        if not replace or active_traces():
            raise ProfileHold("Different plan exists or tunnels were configured; no overwrite")
        # Atomic replace: only explicit confirmation on a pre-activation host.
        stage = path.with_name(".profile-first.tmp-" + str(os.getpid()))
        try:
            fd = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(json.dumps(obj, sort_keys=True) + "\n")
                out.flush()
                os.fsync(out.fileno())
            safe_file(path)
            os.replace(stage, path)
        finally:
            if os.path.lexists(str(stage)):
                os.unlink(stage)
        return "PROFILE_FIRST_REPLACED_BEFORE_ACTIVATION"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(obj, sort_keys=True) + "\n")
        out.flush()
        os.fsync(out.fileno())
    return "PROFILE_FIRST_SAVED_NO_SERVICES_CHANGED"


def output(obj: dict) -> None:
    print(f"FRP_PORT={obj['frp']['port']}")
    print(f"FRP_PATH={obj['frp']['path']}")
    print(f"BACKHAUL_PORT={obj['backhaul']['port']}")
    print(f"BACKHAUL_PATH={obj['backhaul']['path']}")
    print("Profiles contain NO token, UUID or credential.")
    print("No Xray inbound, FRP/Backhaul tunnel or Nginx route was created.")
    print("IR FRP: Once the matching Smite TCP server tunnel is APPLIED,")
    print("the guarded XHTTP sync timer publishes the planned FRP Path.")
    print("Until then PROFILE FIRST is a saved plan, NOT a working client.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_PLAN)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--save", action="store_true")
    actions.add_argument("--show", action="store_true")
    parser.add_argument("--frp-port")
    parser.add_argument("--frp-path")
    parser.add_argument("--backhaul-port")
    parser.add_argument("--backhaul-path")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        if args.show:
            obj = load(args.file)
            if obj is None:
                raise ProfileHold("No saved dual profile on THIS host")
            output(obj)
            return 0
        obj = validate(args.frp_port, args.frp_path,
                       args.backhaul_port, args.backhaul_path)
        if args.check:
            print("PROFILE_FIRST_VALID")
        else:
            if args.replace and args.confirm != "REPLACE-UNAPPLIED-PROFILES":
                raise ProfileHold("Explicit replacement consent required")
            print(store(args.file, obj, replace=args.replace))
        output(obj)
        return 0
    except (ProfileHold, OSError) as exc:
        # Only fixed categories are printed, no configs or tokens.
        print("HOLD: " + str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
