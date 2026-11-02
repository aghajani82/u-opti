# U-OPTI Security Monitoring (System Optimization → 7)

This feature is **opt-in**. Updating U-OPTI adds the menu but does not
activate monitoring, reconfigure Xray, restart services, or change UFW rules.

## Menu

Open U-OPTI → **2) System Optimization → 7) Security Monitoring**.

| Choice | Action |
| --- | --- |
| 1 | Install/enable daily local security reports and recognized Xray 10-day archive policy |
| 2 | Run a report immediately |
| 3 | Print newest report (safe to share after reviewing contents) |
| 4 | List recent saved report filenames |
| 5 | Open a named report |
| 6 | View local monitor status |

Reports: `/var/log/uopti-security/monitor/*.txt` (root-only, mode 0600).
Daily job: `/etc/cron.daily/uopti-security-monitor`.
State: `/var/lib/uopti-security/monitor-state.json` (root-only).
All reports and scanned Xray logs remain on the host; there is no remote
collection, email, webhook, or self-healing action.

## What is checked

- systemd state of Nginx, Docker, Cron, SSH and Fail2ban (if installed);
- disk use and change in public listen ports relative to the previous run;
- Docker running/unhealthy container totals;
- SSH failed-auth journal line count (last 24h);
- counters for the two formerly reported BADBOX IP:80 UFW DROP rules, if present;
- 24h matches for `ycxrl.com` and the known IPv4/IPv6 destination addresses
  in **existing** Sanaei 3x-ui Xray access logs; total log lines, distinct
  matching client labels (no names/UUIDs/raw IPs in the report);
- unreadable/stale Xray logs and local warnings.

The indicator list is a **specific known-IOC check**, not comprehensive
malware or compromise detection. An `accepted` Xray log line does not prove
that a connection reached the destination, and a zero count is not a clean
bill of health. Firewall counters count packets, not infected devices.

## Xray logging and retention

The monitor reads only recognized
`/opt/3x-ui/instances/<numeric>/db/security-logs/access.log*` paths.
It does **not** enable Xray's access logger or alter any live Docker mounts.
If no Xray log is present, system monitoring still functions.

On installation, a recognized existing U-OPTI logrotate config is
validated and changed to `hourly` / `rotate 240` / `maxage 10`,
with a timestamped copy of the former config. If one eligible log exists
and no managed policy exists, the monitor installs a separate hourly
logrotate policy. Unfamiliar configurations fail closed rather than being
overwritten.

Each daily monitor run prunes only recognized **rotated** Xray archives
older than 10 days and old report files. Active `access.log`, Xray
configuration, SQLite databases, and incident snapshot files are preserved.
Age is based on filesystem modification time. `maxsize 16M` and
`rotate 240` mean unusually high log volume can reduce the history below
10 days; the active log can grow between hourly rotations.

Cron is controlled by the host's normal `cron.daily` and `cron.hourly`
mechanisms; the first real rotation should be verified separately.

## Operational boundaries

The feature installs local root-owned files only after confirming choice 1.
It does not change live Xray settings, users, proxies, container names,
Nginx, SSH configuration, UFW, FRP or Smite.

On a legacy fixed-module updater, opening choice 7 can first download two
missing U-OPTI module files from a fixed source commit, using SHA-1 Git blob
integrity verification. This only completes the U-OPTI menu module set;
daily monitoring still requires the user's confirmation in choice 1.

To stop daily reports, the operator may remove the managed
`/etc/cron.daily/uopti-security-monitor` job after backing it up. Keep or
restore a prior logrotate policy deliberately; U-OPTI updates do not
uninstall monitoring from the host.
