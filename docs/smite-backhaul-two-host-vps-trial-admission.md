# Independent Backhaul — two-host VPS trial admission (DRAFT / HOLD)

> **Not an install guide.** This runbook describes evidence to collect from
> two **disposable IR/KH test servers** with recoverable provider snapshots
> and out-of-band console access. The modules currently installed on Stable
> do not yet implement a real-host Backhaul installer. **Do not run these
> commands on production or assume U-OPTI main has these new files.**

## Step 1 — Before touching either test VPS

- Keep stable/main unchanged. Use the reviewed experimental branch only in
  a **deliberately provisioned disposable test environment**, with explicit
  operator approval. Never substitute an active production panel.
- Have a provider snapshot for **both** IR and KH taken after all baseline
  configuration is complete. Confirm the provider records the snapshots;
  for each side independently test a *restore onto a disposable isolated
  clone* where possible. A snapshot's existence is **not** proof of a
  working restore.
- Ensure console or rescue access on **both** test machines independent of
  SSH and independent of the Backhaul/FRP tunnels. Confirm you can use it.
- Review baseline Smite Panel/Node identity and pairing, current working
  inbounds, container/Compose paths, Nginx port 443 and local-only controls.
  Capture only the *results*, not tokens, panel secrets, private keys or
  detailed tunnel configurations.
- Do **not** generate test traffic through the public 443 route yet. No
  snapshot or TLS check is performed by the Python admission modules.

## Step 1A — Safe preliminary inspection without experimental modules

If the disposable VPS does **not** yet have the experimental U-OPTI
branch installed, do **not** fetch and execute an unreviewed installer
as root merely to collect diagnostics. Use the same minimal read-only
commands independently on both machines. These observations are
*not* the structured signed/preflight attestation from Step 2.

**TARGET: IR — disposable Iran-role server only, read-only**

```bash
echo '=== IR READ-ONLY SMITE BASELINE ==='
if test -d /opt/smite-node; then echo 'NODE_DIRECTORY=PRESENT'; else echo 'NODE_DIRECTORY=MISSING'; fi
for file in /opt/smite-node/.env /opt/smite-node/docker-compose.yml; do
  if test -f "$file"; then echo "FILE=$(basename "$file") PRESENT"; else echo "FILE=$(basename "$file") MISSING"; fi
done
if test -f /opt/smite-node/.env; then
  awk -F= '$1 ~ /^(NODE_ROLE|SMITE_ENGINE_INVENTORY_MODE|SMITE_AGENT_AUTH_MODE|SMITE_NODE_PANEL_AUTH_MODE)$/ {v=$2; gsub(/[^A-Za-z0-9_-]/,"?",v); print $1 "=" v}' /opt/smite-node/.env
fi
if command -v docker >/dev/null 2>&1; then
  docker inspect --type=container --format 'NODE_RUNNING={{.State.Running}} NETWORK={{.HostConfig.NetworkMode}} IMAGE={{.Config.Image}}' smite-node 2>/dev/null || echo 'NODE_CONTAINER=NOT_FOUND'
  docker inspect --type=container --format '{{range .Mounts}}MOUNT={{.Destination}} TYPE={{.Type}} NAME={{.Name}}{{println}}{{end}}' smite-node 2>/dev/null || true
else echo 'DOCKER=NOT_INSTALLED'; fi
```

**TARGET: KH — disposable foreign-role server only, read-only**

Run the **same block**, changing only the first line to:

```bash
echo '=== KH READ-ONLY SMITE BASELINE ==='
```

These commands disclose only an allowed set of non-secret mode fields
and Docker container/mount metadata; they do not print `.env`
contents, volume source paths, identity files or any tunnel tokens.
They do not restart Docker, connect to another server or modify disks.
The container image string might contain a private image name; review
the output before sharing it. Both sides may be physically overseas,
but their roles must still be separately `IR` and `KH`.

## Step 2 — Independently collect read-only, redacted reports

Only if you **already have the experimental modules installed** on two
approved *disposable* hosts (this is not a command to install them):

**IR — disposable Iran-role test VPS, read only**

```bash
# TARGET: IR TEST SERVER — READ ONLY
sudo python3 -B /usr/local/lib/u-opti/modules/smite-managed-backhaul-host-gate.py \
  --node-dir /opt/smite-node --format json
```

**KH — disposable foreign-role test VPS, read only**

```bash
# TARGET: KH TEST SERVER — READ ONLY
sudo python3 -B /usr/local/lib/u-opti/modules/smite-managed-backhaul-host-gate.py \
  --node-dir /opt/smite-node --format json
```

A correct report always contains `"HOST_INSTALL_AUTHORIZED":"NO"` and
`"BACKHAUL_ACTIVATION_GATE":"HOLD"`, **and the command exits with status 2
by design**. An eligible `HOST_PREFLIGHT` can be
`PASS_LOCAL_ONLY_INCOMPLETE` — never `READY_TO_INSTALL`.

The report contains a limited set of status codes and a Compose SHA256:
**no IP addresses, paths, Docker environment, tunnel specs, pairing tokens,
passwords or identity keys**. Do not send raw Docker inspection output,
`.env` content, full `docker compose config`, node-identity JSON or
snapshot-provider account credentials.

The gate recognizes Smite's real config **bind** mount at
`./config:/etc/smite-node` AND its durable **named Docker volume**
`smite-node-data` at `/var/lib/smite-node`. It refuses an unexpected
volume, mount, image reference or active stored tunnel. It makes just one
`docker inspect` read-only request and does **not** contact the Panel,
restart a container or change firewall/Nginx.

## Step 3 — Compare both reports offline

On an offline review machine with Python 3 and a checkout of the same
experimental U-OPTI branch, save **only the sanitized JSON outputs** as
`ir.json` and `kh.json`.

**REVIEW COMPUTER — not IR/KH, offline**

```bash
# TARGET: OFFLINE REVIEW COMPUTER — READ ONLY
python3 modules/smite-managed-backhaul-pair-review.py \
  --ir-report ir.json --kh-report kh.json
```

The comparison rejects swapped roles, invalid/altered report schemas,
fabricated Snapshot/443 verification flags, and existing persisted tunnels.
It labels both inputs `USER_SUPPLIED_UNAUTHENTICATED`. **It always exits
status 2 and always returns `HOST_INSTALL_AUTHORIZED=NO`**. Exchanging
files does not establish authenticated remote attestations.

## Step 4 — Evidence still required before a separately approved host trial

| Evidence | IR | KH | Automatic check today |
| --- | --- | --- | --- |
| Disposable host, intended role, managed-strict Smite Core | Required | Required | Local read-only |
| Correct named data volume and no active saved tunnels | Required | Required | Local read-only |
| Provider snapshot created and restore verified on safe clone | Required | Required | **Manual only** |
| Independent emergency console tested | Required | Required | **Manual only** |
| Signed Panel→Node pairing + preserved HMAC replay state | Required | Required | CI-only, **not remote host** |
| Nginx TLS 443, single public entry and correct firewall rules | Required | Required | **Not checked remotely** |
| Real-host Docker recreate, automatic rollback, no FRP side effects | Required | Required | CI sandbox only |
| Independently installed Backhaul on both ends | Not yet | Not yet | **Not authorized** |
| Smite Create Tunnel with dynamic Xray inbound, 443 transport | Not yet | Not yet | **Not authorized** |

**HOLD:** Until these steps pass under separate review, no trial admission
can permit a real VPS change. Do not merge either Draft PR or unlock
`Install Backhaul` on a real host. A good offline report does not mean a
working snapshot, a valid public TLS route or uninterrupted active tunnels.
