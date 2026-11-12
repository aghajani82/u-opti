#!/usr/bin/env python3
"""Existing RC7 foreign runtime read-only witness adapter (trial, NOT activated).

Feeds independently observed CORE/SANAEI/GATEWAY truth to the disposable
host recovery rehearsal. No installer, mutation, downgrade, or real-host CLI.

Reuses:
- Smite's exact paired-image Cosign/OIDC trial verifier;
- U-OPTI's already-reviewed RC7 Compose ownership/paused/strict helpers;
- the existing Foreign Gateway/443 read-only preflight; and
- the existing root-owned Sanaei instance DB path validator.
The witnesses must NEVER claim ABSENT on an unknown/partially altered host.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
from urllib.parse import urlsplit


class Hold(ValueError):
    pass


def deny():
    raise Hold("Foreign existing-runtime witness HOLD; host state is not proven")


def load(name, filename):
    path = Path(__file__).with_name(filename)
    if path.is_symlink() or not path.is_file():
        deny()
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        deny()
    obj = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = obj
    spec.loader.exec_module(obj)
    return obj


TRIAL_NODE = ("ghcr.io/aghajani82/smite-node@sha256:"
              "587a131156736961c86fa91f33f013d28eb85e606ab0ab4335969fabfd881483")
TRIAL_PANEL = ("ghcr.io/aghajani82/smite-panel@sha256:"
               "1b03d0d865ba4abd6fe45899d2ccd6d34f300b4804acd2c6690a52b68fb26289")
SOURCE = "b865be93e22153c60769f6329e6e55e781494ded"
MANIFEST_SHA = "e13f0708b1de5eef112b955f4b6efe4e1efa5520d404458646bb6e1e76c96608"
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


def bind_existing(*, pairing=None, signature_runner=subprocess.run):
    """Bind existing read-only RC7 verifiers; never an installation entry."""
    signed = load("uopti_witness_trial_signatures",
                  "smite-unified-trial-pair-admission.py")
    mount = load("uopti_witness_sanaei_mount",
                 "smite-rc5-xhttp-sanaei-mount.py")
    plan = load("uopti_witness_gateway_plan",
                "smite-unified-foreign-gateway-plan.py")
    if pairing is None:
        pairing = load("uopti_witness_pairing", "smite-node-pairing.py")

    def verify_signed():
        return signed.verify(
            manifest=Path(__file__).with_name("smite-unified-trial-registry-pair.json"),
            manifest_sha256=MANIFEST_SHA, source_sha=SOURCE,
            trusted_root=Path(__file__).with_name("smite-rc7-sigstore-trusted-root.json"),
            runner=signature_runner)

    def site_for(scope):
        domain = urlsplit(scope["origin"]).hostname
        shared = Path("/etc/nginx/sites-available") / ("3xui-" + domain)
        standalone = Path("/etc/nginx/sites-available") / domain
        if shared.exists() or shared.is_symlink():
            data = plan.safe_site(shared)
            if data is None:
                deny()
            if "# U-OPTI-MANAGED-3XUI-NGINX" in data:
                return shared
        return standalone

    return ExistingWitnesses(
        pairing=pairing, verify_signed=verify_signed,
        validate_db=mount._validate_instance_db,
        gateway_site=site_for)


class ExistingWitnesses:
    def __init__(self, *, pairing, verify_signed, validate_db, gateway_site):
        """All injected functions read only. No CLI can instantiate these."""
        self.pairing = pairing
        self.verify_signed = verify_signed
        self.validate_db = validate_db
        self.gateway_site = gateway_site
        self._signed_scope = None

    def _signed(self):
        if self._signed_scope is None:
            result = self.verify_signed()
            if (not isinstance(result, dict)
                    or result.get("status") != "verified_trial_pair"
                    or result.get("source_sha") != SOURCE
                    or result.get("panel") != TRIAL_PANEL
                    or result.get("node") != TRIAL_NODE
                    or result.get("host_activation_allowed") is not False
                    or getattr(self.pairing, "_FOREIGN_NODE_IMAGE_UNIFIED_TRIAL", None)
                    != TRIAL_NODE):
                deny()
            self._signed_scope = result

    def _state(self, scope):
        p = self.pairing
        state = p.state_values()
        if (not isinstance(scope, dict)
                or state.get("SMITE_ROLE") != "foreign"
                or state.get("SMITE_MANAGED_VERSION") != "2.0.0-rc.7"
                or state.get("SMITE_CONNECTION_MODE") != "standard"
                or state.get("SMITE_NODE_NAME") != scope.get("node_name")
                or state.get("SMITE_PANEL_DOMAIN") != urlsplit(scope["panel_url"]).hostname
                or state.get("SMITE_FOREIGN_DOMAIN") != urlsplit(scope["origin"]).hostname
                or urlsplit(scope["control_url"]).hostname != state.get("SMITE_FOREIGN_DOMAIN")
                or not re.fullmatch(r"/smite-node/[0-9a-f]{32}",
                                    urlsplit(scope["control_url"]).path)):
            deny()
        return state

    def _compose(self):
        p = self.pairing
        command = p._rc7_foreign_compose_command()
        raw = p._run(command + ["config", "--format", "json"],
                     capture=True, timeout=30)
        try:
            doc = json.loads(raw)
            service = doc["services"]["smite-node"]
            env = service["environment"]
            mounts = service.get("volumes", [])
            if (service.get("image") != TRIAL_NODE
                    or service.get("network_mode") != "host"
                    or service.get("ports") or service.get("privileged")
                    or service.get("cap_add") not in (
                        ["NET_ADMIN", "SYS_MODULE"], ["SYS_MODULE", "NET_ADMIN"])
                    or service.get("devices") not in (
                        ["/dev/net/tun:/dev/net/tun"],
                        ["/dev/net/tun:/dev/net/tun:rwm"],
                        [{"source": "/dev/net/tun", "target": "/dev/net/tun",
                          "permissions": "rwm"}])
                    or not isinstance(service.get("command"), list)
                    or service["command"][:6] != [
                        "uvicorn", "main:app", "--host", "127.0.0.1",
                        "--port", "8888"]
                    or env.get("NODE_ROLE") != "foreign"):
                deny()
            selected = [x for x in mounts if isinstance(x, dict)
                        and x.get("target") == "/run/smite-sanaei-ro"]
            if len(selected) != 1 or selected[0].get("read_only") is not True:
                deny()
            return env, selected[0]
        except (KeyError, TypeError, ValueError, AttributeError):
            deny()

    def core(self, scope):
        """The NEW, *unpaired* RC7 trial Node is running paused and strict."""
        try:
            self._signed()
            state = self._state(scope)
            p = self.pairing
            p._require_no_active_engine_overlays()
            env, _mount = self._compose()
            file_env = p._env_map(p._regular(
                p.NODE_DIR / ".env", mode=0o600, limit=64_000))
            runtime = p._run(
                ["docker", "inspect", "-f",
                 "{{range .Config.Env}}{{println .}}{{end}}", "smite-node"],
                capture=True, timeout=10).splitlines()
            if (p._run(["docker", "inspect", "-f", "{{.Config.Image}}", "smite-node"],
                       capture=True, timeout=10) != TRIAL_NODE
                    or p._run(["docker", "inspect", "-f", "{{.State.Health.Status}}",
                               "smite-node"], capture=True, timeout=10) != "healthy"):
                deny()
            running = p._run(["docker", "inspect", "-f", "{{.Image}}", "smite-node"],
                             capture=True, timeout=10)
            local = p._run(["docker", "image", "inspect", "-f", "{{.Id}}",
                            TRIAL_NODE], capture=True, timeout=10)
            if not IMAGE_ID.fullmatch(running) or local != running:
                deny()
            for key, value in (
                ("SMITE_NODE_PANEL_AUTH_MODE", "paused"),
                ("SMITE_AGENT_AUTH_MODE", "strict"),
                ("SMITE_ENGINE_INVENTORY_MODE", "managed"),
                ("PANEL_ADDRESS", state["SMITE_PANEL_DOMAIN"] + ":443"),
                ("NODE_ROLE", "foreign"),
                ("NODE_NAME", state["SMITE_NODE_NAME"]),
            ):
                # Disk config and effective Compose must both match.
                for values in (file_env, env):
                    if values.get(key) != value:
                        deny()
                if key in ("SMITE_NODE_PANEL_AUTH_MODE", "SMITE_AGENT_AUTH_MODE",
                           "SMITE_ENGINE_INVENTORY_MODE"):
                    if runtime.count(key + "=" + value) != 1 or sum(
                        x.startswith(key + "=") for x in runtime) != 1:
                        deny()
            return True
        except (OSError, TypeError, ValueError, KeyError, AttributeError,
                self.pairing.WizardHold):
            return False

    def sanaei(self, scope):
        """ABSENT only for the EXACT baseline empty RO mount; else DRIFT."""
        try:
            if self.core(scope) is not True:
                return "DRIFT"
            p = self.pairing
            env, mount = self._compose()
            file_env = p._env_map(p._regular(
                p.NODE_DIR / ".env", mode=0o600, limit=64_000))
            source = mount.get("source")
            # No attached data yet: exact fresh placeholder only.
            empty = str(p.NODE_DIR / ".sanaei-empty")
            if (env.get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
                    and file_env.get("SMITE_SANAEI_INVENTORY_ENABLED") == "false"
                    and file_env.get("SMITE_SANAEI_DB_HOST_PATH") == empty
                    and source == empty):
                return "ABSENT"
            if (env.get("SMITE_SANAEI_INVENTORY_ENABLED") != "true"
                    or file_env.get("SMITE_SANAEI_INVENTORY_ENABLED") != "true"
                    or source != "/opt/3x-ui/instances/01/db"
                    or file_env.get("SMITE_SANAEI_DB_HOST_PATH") != source):
                return "DRIFT"
            # Call the ALREADY EXISTING trusted DB instance verifier.
            if self.validate_db(Path("/"), "01") != source:
                return "DRIFT"
            # Exact read-only container-side mounted schema verification
            # from the prior RC7 Sanaei installation routine, no UPDATE/PRAGMA
            # mutation and no client records are read.
            probe = (
                'import os,sqlite3,stat,urllib.parse; '
                'p="/run/smite-sanaei-ro/x-ui.db"; d="/run/smite-sanaei-ro"; '
                's=os.stat(p); assert stat.S_ISREG(s.st_mode); '
                'target=urllib.parse.quote(d,safe="/"); '
                'rows=[x.split() for x in open("/proc/self/mountinfo") '
                'if len(x.split()) > 5]; '
                'assert any(urllib.parse.unquote(x[4])==target '
                'and "ro" in x[5].split(",") for x in rows); '
                'c=sqlite3.connect("file:"+p+"?mode=ro",uri=True,timeout=1); '
                'c.execute("PRAGMA query_only=ON"); '
                'cols={r[1] for r in c.execute("PRAGMA table_info(inbounds)")}; '
                'assert {"port","listen","protocol","stream_settings","enable"} <= cols'
            )
            p._run(["docker", "exec", "smite-node", "python", "-c", probe],
                   timeout=15)
            return "READY"
        except (OSError, TypeError, ValueError, KeyError, AttributeError,
                self.pairing.WizardHold):
            return "DRIFT"

    def gateway(self, scope):
        """Use the existing full RC7 443 preflight; never mutate Nginx."""
        try:
            if self.core(scope) is not True:
                return "DRIFT"
            p = self.pairing
            path = p.STATE.parent / "foreign-gateway.env"
            site = self.gateway_site(scope)
            if (not isinstance(site, Path)
                    or site.is_symlink()
                    or not site.is_absolute()):
                return "DRIFT"
            if not path.exists() and not path.is_symlink():
                # A missing Gateway receipt is not evidence that an old
                # location or Node address was never installed.
                env = p._env_map(p._regular(
                    p.NODE_DIR / ".env", mode=0o600, limit=64_000))
                if env.get("SMITE_CONTROL_ADDRESS"):
                    return "DRIFT"
                if site.is_file():
                    data = site.read_text(encoding="utf-8")
                    if "/smite-node/" in data:
                        return "DRIFT"
                return "ABSENT"
            if path.is_symlink() or not path.is_file():
                return "DRIFT"
            if self.sanaei(scope) != "READY":
                return "DRIFT"
            state = self._state(scope)
            panel, domain, url = p._foreign_gateway_preflight(
                state, review_unified_trial=True)
            if (panel != urlsplit(scope["panel_url"]).hostname
                    or domain != urlsplit(scope["origin"]).hostname
                    or urlsplit(url).path != urlsplit(scope["control_url"]).path):
                return "DRIFT"
            # The pre-existing helper independently performs real TLS
            # certificate-verifying loopback HTTPS/443 root readiness and
            # full effective Compose/RO mount inspection.
            return "READY"
        except (OSError, UnicodeError, TypeError, ValueError, KeyError,
                AttributeError, self.pairing.WizardHold):
            return "DRIFT"


def review_only_status():
    return {
        "mode": "TRIAL_ADAPTER_NOT_HOST_WIRED",
        "host_mutations": False,
        "connected": False,
        "activation_allowed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", required=True)
    parser.parse_args(argv)
    print("EXISTING_FOREIGN_WITNESSES=TRIAL_ONLY")
    print("HOST_EXECUTION=NOT_AUTHORIZED")
    print("ACTIVATION_ALLOWED=NO")
    print("FOREIGN_CONNECTED=NOT_PROVEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
