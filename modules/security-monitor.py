#!/usr/bin/env python3
"""U-OPTI opt-in, local-only security monitor (no service or firewall mutations)."""
import argparse
import datetime as dt
import gzip
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

CONF = Path("/etc/uopti-security/xray-logrotate.conf")
ROTATE_CRON = Path("/etc/cron.hourly/uopti-xray-logrotate")
REPORTS = Path("/var/log/uopti-security/monitor")
STATE = Path("/var/lib/uopti-security/monitor-state.json")
DAILY = Path("/etc/cron.daily/uopti-security-monitor")
SELF = Path("/usr/local/lib/u-opti/modules/security-monitor.py")
INSTANCES = Path("/opt/3x-ui/instances")
INDICATORS = ("ycxrl.com", "64.62.203.98", "2001:470:575::97")
RETAIN_DAYS = 10
ROTATIONS = 240
STAMP_RE = re.compile(r"^(\d{4})[/\-](\d{2})[/\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
EMAIL_RE = re.compile(r"\bemail:\s*([^\s\]]+)", re.I)
ARCHIVE_RE = re.compile(r"access\.log\.\d+(?:\.gz)?$")
REPORT_RE = re.compile(r"\d{8}T\d{6}Z\.txt$")
CRON_MARKER = "# U-OPTI-SECURITY-MONITOR MANAGED"

def run_cmd(*args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           check=False)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None

def secure_dir(path):
    if path.is_symlink():
        raise RuntimeError("HOLD: symlink directory: " + str(path))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.stat().st_uid != 0:
        raise RuntimeError("HOLD: directory not owned by root: " + str(path))
    path.chmod(0o700)

def atomic_file(path, content, mode=0o600):
    secure_dir(path.parent)
    if path.is_symlink():
        raise RuntimeError("HOLD: refusing symlink: " + str(path))
    fd, temp = tempfile.mkstemp(prefix=".uopti-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def known_logdirs():
    if not INSTANCES.is_dir() or INSTANCES.is_symlink():
        return []
    result = []
    for item in sorted(INSTANCES.iterdir()):
        if not re.fullmatch(r"[0-9]{2,}", item.name) or item.is_symlink():
            continue
        logdir = item / "db" / "security-logs"
        if not logdir.is_symlink() and logdir.is_dir() and logdir.stat().st_uid == 0:
            result.append(logdir)
    return result

def validate_logrotate(body):
    if not shutil.which("logrotate"):
        raise RuntimeError("HOLD: logrotate is not installed")
    fd, tmp = tempfile.mkstemp(prefix=".logrotate-validate-", dir="/tmp")
    os.close(fd)
    try:
        Path(tmp).write_text(body, encoding="utf-8")
        p = subprocess.run(["logrotate", "-d", "-s", "/dev/null", tmp],
                           capture_output=True, text=True, timeout=15)
        if p.returncode != 0:
            raise RuntimeError("HOLD: invalid logrotate configuration")
    finally:
        os.unlink(tmp)

def configure_retention(logdirs):
    """Only modify a recognizable preexisting config or create for one existing log."""
    if CONF.is_symlink() or ROTATE_CRON.is_symlink():
        raise RuntimeError("HOLD: unsafe logrotate path")
    if CONF.exists():
        if not CONF.is_file() or CONF.stat().st_uid != 0:
            raise RuntimeError("HOLD: logrotate config not root-owned regular file")
        original = CONF.read_text(encoding="utf-8")
        # Never replace an unknown policy or modify third-party logrotate files.
        if "security-logs/access.log" not in original or original.count("{") != 1:
            raise RuntimeError("HOLD: unexpected existing Xray logrotate configuration")
        body = original
        for key, allowed, new in (("rotate", {"48", "168", "240"}, "240"),
                                  ("maxage", {"3", "7", "10"}, "10")):
            pat = re.compile(r"(?m)^([ \t]*" + key + r"[ \t]+)(\d+)([ \t]*)$")
            matches = list(pat.finditer(body))
            if len(matches) != 1 or matches[0].group(2) not in allowed:
                raise RuntimeError("HOLD: unrecognized " + key + " setting")
            body = pat.sub(lambda m: m.group(1) + new + m.group(3), body, count=1)
        validate_logrotate(body)
        if body != original:
            backup = CONF.with_name(CONF.name + ".bak." +
                                    dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            if backup.exists():
                raise RuntimeError("HOLD: backup collision")
            atomic_file(backup, original)
            atomic_file(CONF, body)
            return "UPDATED_EXISTING_POLICY;BACKUP=" + str(backup)
        return "ALREADY_10_DAYS"
    eligible = [p / "access.log" for p in logdirs
                if (p / "access.log").is_file() and not (p / "access.log").is_symlink()]
    if len(eligible) != 1:
        return "NO_MANAGED_XRAY_LOG_POLICY (host monitoring still available)"
    target = eligible[0]
    body = (str(target) + " {\n    hourly\n    rotate 240\n"
            "    maxage 10\n    maxsize 16M\n    missingok\n"
            "    notifempty\n    compress\n    delaycompress\n"
            "    copytruncate\n    su root root\n}\n")
    validate_logrotate(body)
    if ROTATE_CRON.exists():
        # Existing unrecognized hourly job must not be changed or silently reused.
        existing = ROTATE_CRON.read_text(encoding="utf-8")
        if str(CONF) not in existing or "logrotate" not in existing:
            raise RuntimeError("HOLD: unexpected existing hourly logrotate job")
    atomic_file(CONF, body)
    if not ROTATE_CRON.exists():
        cron = ("#!/bin/sh\n/usr/sbin/logrotate -s "
                "/var/lib/logrotate/uopti-xray-access.status "
                + str(CONF) + "\n")
        atomic_file(ROTATE_CRON, cron, 0o700)
    return "CREATED_10_DAY_POLICY"

def install():
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    if not SELF.is_file() or SELF.is_symlink():
        raise RuntimeError("HOLD: U-OPTI monitor module missing")
    secure_dir(REPORTS)
    secure_dir(STATE.parent)
    logdirs = known_logdirs()
    retention = configure_retention(logdirs)
    if DAILY.exists():
        if DAILY.is_symlink() or not DAILY.is_file() or DAILY.stat().st_uid != 0:
            raise RuntimeError("HOLD: unsafe existing daily job")
        if CRON_MARKER not in DAILY.read_text(encoding="utf-8"):
            raise RuntimeError("HOLD: unrelated daily job exists at same path")
    cron = ("#!/bin/sh\n" + CRON_MARKER + "\n"
            "/usr/bin/python3 -B " + str(SELF) +
            " run --quiet || /usr/bin/logger -p user.err "
            "-t uopti-security 'monitor run failed'\n")
    atomic_file(DAILY, cron, 0o700)
    print("INSTALL=PASS")
    print("RETENTION_POLICY=" + retention)
    print("DAILY_REPORT=ENABLED")
    print("XRAY_LOGGING_CHANGES=NONE")
    print("SERVICE_RESTARTS=NONE")
    print("NOTE=Monitoring reads existing Xray logs; it does not enable access logging.")
    generate_report()

def _counter(program, chain, address):
    raw = run_cmd(program, "-nvx", "-L", chain)
    if raw is None:
        return None
    matches = [x.split() for x in raw.splitlines()
               if address in x and "DROP" in x and "dpt:80" in x]
    if len(matches) == 1 and matches[0][0].isdigit():
        return int(matches[0][0])
    return None

def _load_state():
    try:
        if STATE.is_file() and not STATE.is_symlink():
            data = json.loads(STATE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}

def prune(now):
    cutoff = (now - dt.timedelta(days=RETAIN_DAYS)).timestamp()
    for f in REPORTS.iterdir():
        if f.is_symlink() or not f.is_file() or not REPORT_RE.fullmatch(f.name):
            continue
        if f.stat().st_mtime < cutoff:
            f.unlink()
    # Only recognized rotated archives; never active log or incident snapshots.
    for logdir in known_logdirs():
        for f in logdir.iterdir():
            if f.is_symlink() or not f.is_file() or not ARCHIVE_RE.fullmatch(f.name):
                continue
            if f.stat().st_mtime < cutoff:
                f.unlink()

def generate_report(quiet=False):
    if os.geteuid() != 0:
        raise RuntimeError("Root required")
    secure_dir(REPORTS)
    secure_dir(STATE.parent)
    now = dt.datetime.now().astimezone()
    since = now - dt.timedelta(hours=24)
    records = []; warnings = []
    def put(key, value):
        records.append(key + "=" + str(value))
    put("CHECK_TIME", now.isoformat())
    for service in ("nginx", "docker", "cron", "fail2ban", "ssh"):
        status = run_cmd("systemctl", "is-active", service) or "UNAVAILABLE"
        put("SERVICE_" + service.upper(), status)
        # A service absent by design is informational.
        if status not in ("active", "UNAVAILABLE", "inactive"):
            warnings.append("SERVICE_CHECK:" + service)
    disk = run_cmd("df", "-P", "/")
    if disk and len(disk.splitlines()) >= 2:
        parts = disk.splitlines()[1].split()
        if len(parts) >= 5 and parts[4].endswith("%"):
            used = int(parts[4][:-1])
            put("DISK_USED_PERCENT", used)
            if used >= 80:
                warnings.append("DISK_HIGH")
    else:
        warnings.append("DISK_CHECK_UNAVAILABLE")
    container = run_cmd("docker", "ps", "--format", "{{.Names}}|{{.Status}}")
    if container is not None:
        container_rows = [x for x in container.splitlines() if x]
        put("RUNNING_CONTAINERS", len(container_rows))
        unhealthy = sum("unhealthy" in x.lower() for x in container_rows)
        put("UNHEALTHY_CONTAINERS", unhealthy)
        if unhealthy:
            warnings.append("DOCKER_UNHEALTHY")
    else:
        put("RUNNING_CONTAINERS", "UNAVAILABLE")
    prev = _load_state(); current = {}
    for family, program, chain, addr in (
        ("IPV4", "iptables", "ufw-user-output", INDICATORS[1]),
        ("IPV6", "ip6tables", "ufw6-user-output", INDICATORS[2])):
        n = _counter(program, chain, addr)
        put(family + "_BLOCK_COUNTER", n if n is not None else "NOT_CONFIGURED")
        if n is not None:
            current[family] = n
            old = prev.get(family)
            if isinstance(old, int) and n > old:
                warnings.append("NEW_BLOCKED_PACKETS:" + family)
            if isinstance(old, int) and n < old:
                warnings.append("FIREWALL_COUNTER_RESET:" + family)
    attempts = run_cmd("journalctl", "-u", "ssh", "--since", "24 hours ago",
                       "--no-pager", "-o", "cat", timeout=25)
    put("SSH_FAILED_AUTH_LINES_24H", sum(
        "Failed password" in line or "Invalid user" in line
        for line in (attempts or "").splitlines()) if attempts is not None else "UNAVAILABLE")
    ports = run_cmd("ss", "-H", "-lnt")
    public = set()
    if ports is not None:
        for line in ports.splitlines():
            cols = line.split()
            if len(cols) < 4: continue
            addr = cols[3]
            host, sep, port = addr.rpartition(":")
            if sep and host in ("*", "0.0.0.0", "[::]", "::") and port.isdigit():
                public.add(int(port))
    put("PUBLIC_LISTEN_PORTS", ",".join(map(str, sorted(public))) or "NONE")
    hist = Counter(); client_labels = set()
    total = 0; errors = 0; newest = None; logfiles = 0
    # Host local timezone is assumed; if Xray uses a different timezone this
    # daily 24-hour window is approximate. No raw client IPs/UUIDs are printed.
    for directory in known_logdirs():
        for p in directory.iterdir():
            if p.is_symlink() or not p.is_file() or (
                p.name != "access.log" and not ARCHIVE_RE.fullmatch(p.name)):
                continue
            logfiles += 1
            op = gzip.open if p.suffix == ".gz" else open
            try:
                with op(p, "rt", errors="replace") as stream:
                    for line in stream:
                        m = STAMP_RE.match(line)
                        if not m: continue
                        try:
                            when = dt.datetime(*map(int, m.groups()),
                                               tzinfo=now.tzinfo)
                        except ValueError:
                            continue
                        if newest is None or when > newest:
                            newest = when
                        if when < since or when > now + dt.timedelta(minutes=5):
                            continue
                        total += 1
                        lower = line.lower()
                        if any(x in lower for x in INDICATORS):
                            for indicator in INDICATORS:
                                if indicator in lower: hist[indicator] += 1
                            match = EMAIL_RE.search(line)
                            if match:
                                client_labels.add(match.group(1).lower())
            except (OSError, EOFError):
                errors += 1
    put("XRAY_FILES_SCANNED", logfiles)
    put("XRAY_ENTRIES_24H", total)
    put("BADBOX_DOMAIN_24H", hist[INDICATORS[0]])
    put("BADBOX_IPV4_24H", hist[INDICATORS[1]])
    put("BADBOX_IPV6_24H", hist[INDICATORS[2]])
    put("BADBOX_DISTINCT_CLIENT_LABELS_24H", len(client_labels))
    put("XRAY_LAST_LOG_ENTRY", newest.isoformat() if newest else "NONE")
    if sum(hist.values()): warnings.append("BADBOX_INDICATOR_PRESENT")
    if errors: warnings.append("XRAY_READ_ERRORS:" + str(errors))
    if logfiles and (newest is None or now - newest > dt.timedelta(hours=6)):
        warnings.append("XRAY_LOG_STALE_OR_TIMEZONE_MISMATCH")
    put("WARNINGS", ";".join(warnings) or "NONE")
    filename = now.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ.txt")
    atomic_file(REPORTS / filename, "\n".join(records) + "\n")
    if current:
        atomic_file(STATE, json.dumps(current, sort_keys=True) + "\n")
    prune(now)
    if not quiet:
        print("\n".join(records))
        print("REPORT=" + str(REPORTS / filename))
    return 0

def latest():
    if not REPORTS.is_dir(): print("No reports. Choose Install or Run now."); return
    files = sorted((p for p in REPORTS.iterdir() if REPORT_RE.fullmatch(p.name)
                    and p.is_file() and not p.is_symlink()), reverse=True)
    if not files: print("No reports."); return
    print(files[0].read_text(encoding="utf-8"))

def list_reports():
    if not REPORTS.is_dir(): print("No reports."); return
    files = sorted((p for p in REPORTS.iterdir() if REPORT_RE.fullmatch(p.name)
                    and p.is_file() and not p.is_symlink()), reverse=True)
    for p in files[:30]:
        print(p.name)

def show_report(name):
    if not REPORT_RE.fullmatch(name):
        raise RuntimeError("Invalid report filename")
    path = REPORTS / name
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Report not found")
    print(path.read_text(encoding="utf-8"))

def status():
    print("MONITOR_DAILY=" + ("INSTALLED" if DAILY.is_file() and not DAILY.is_symlink() else "NOT_INSTALLED"))
    print("XRAY_LOG_POLICY=" + ("PRESENT" if CONF.is_file() and not CONF.is_symlink() else "NOT_INSTALLED"))
    print("XRAY_LOG_DIRECTORIES=" + str(len(known_logdirs())))
    print("REPORTS=" + str(REPORTS))
    print("RETENTION_DAYS=" + str(RETAIN_DAYS))
    print("NOTE=No automatic blocking, restarts or panel changes.")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "status", "run", "latest", "list", "show"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "install": install()
        elif args.action == "status": status()
        elif args.action == "run": generate_report(quiet=args.quiet)
        elif args.action == "latest": latest()
        elif args.action == "list": list_reports()
        elif args.action == "show": show_report(args.name or "")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("HOLD: " + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
