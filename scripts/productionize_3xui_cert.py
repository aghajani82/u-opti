from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old!r}")
    p.write_text(text.replace(old, new, 1))


# Fresh-install packaging.
replace_once(
    "install.sh",
    '    "docker-3xui-instance.sh"\n    "docker-3xui-compat.sh"',
    '    "docker-3xui-instance.sh"\n    "docker-3xui-certificate-multi.sh"\n    "docker-3xui-compat.sh"',
)
replace_once(
    "install.sh",
    '        docker-3xui-instance.sh) LABEL="3x-UI Instance Management" ;;\n        docker-3xui-compat.sh)',
    '        docker-3xui-instance.sh) LABEL="3x-UI Instance Management" ;;\n        docker-3xui-certificate-multi.sh) LABEL="3x-UI Multi-Instance TLS Certificates" ;;\n        docker-3xui-compat.sh)',
)
replace_once(
    "install.sh",
    '   ! grep -q \'show_smite_easytier_menu()\' "$TEMP_DIR/smite-easytier.sh" || \\\n   ! grep -q \'show_smite_menu()\' "$TEMP_DIR/smite.sh"; then',
    '   ! grep -q \'show_smite_easytier_menu()\' "$TEMP_DIR/smite-easytier.sh" || \\\n   ! grep -q \'docker_3xui_multi_certificate_menu()\' "$TEMP_DIR/docker-3xui-certificate-multi.sh" || \\\n   ! grep -q \'show_smite_menu()\' "$TEMP_DIR/smite.sh"; then',
)
replace_once(
    "install.sh",
    'echo "3x-UI Docker Module:"\necho "$MODULES_PATH/docker-3xui.sh"\necho\n\necho "3x-UI Nginx / SSL Module:"',
    'echo "3x-UI Docker Module:"\necho "$MODULES_PATH/docker-3xui.sh"\necho\n\necho "3x-UI Multi-Instance TLS Certificate Module:"\necho "$MODULES_PATH/docker-3xui-certificate-multi.sh"\necho\n\necho "3x-UI Nginx / SSL Module:"',
)

# Runtime loading and self-updater packaging.
replace_once(
    "u-opti",
    'source "$MODULES_PATH/docker-3xui-instance.sh"\nsource "$MODULES_PATH/docker-3xui-nginx.sh"',
    'source "$MODULES_PATH/docker-3xui-instance.sh"\nsource "$MODULES_PATH/docker-3xui-certificate-multi.sh"\nsource "$MODULES_PATH/docker-3xui-nginx.sh"',
)
replace_once(
    "u-opti",
    '                "docker-3xui-instance.sh"\n                "docker-3xui.sh"',
    '                "docker-3xui-instance.sh"\n                "docker-3xui-certificate-multi.sh"\n                "docker-3xui.sh"',
)
replace_once(
    "u-opti",
    '                ["docker-3xui-instance.sh"]="$BASE_URL/modules/docker-3xui-instance.sh"\n                ["docker-3xui.sh"]=',
    '                ["docker-3xui-instance.sh"]="$BASE_URL/modules/docker-3xui-instance.sh"\n                ["docker-3xui-certificate-multi.sh"]="$BASE_URL/modules/docker-3xui-certificate-multi.sh"\n                ["docker-3xui.sh"]=',
)
replace_once(
    "u-opti",
    '                ["docker-3xui-instance.sh"]="$TEMP_DIR/docker-3xui-instance.sh"\n                ["docker-3xui.sh"]=',
    '                ["docker-3xui-instance.sh"]="$TEMP_DIR/docker-3xui-instance.sh"\n                ["docker-3xui-certificate-multi.sh"]="$TEMP_DIR/docker-3xui-certificate-multi.sh"\n                ["docker-3xui.sh"]=',
)
replace_once(
    "u-opti",
    '               ! grep -q \'show_smite_foreign_gateway_menu()\' "$TEMP_DIR/smite-foreign-gateway.sh"; then',
    '               ! grep -q \'show_smite_foreign_gateway_menu()\' "$TEMP_DIR/smite-foreign-gateway.sh" || \\\n               ! grep -q \'docker_3xui_multi_certificate_menu()\' "$TEMP_DIR/docker-3xui-certificate-multi.sh"; then',
)
# BACKUP_FILES contains the same anchor a second time after UPDATE_FILE_NAMES was changed.
replace_once(
    "u-opti",
    '                "docker-3xui-instance.sh"\n                "docker-3xui.sh"',
    '                "docker-3xui-instance.sh"\n                "docker-3xui-certificate-multi.sh"\n                "docker-3xui.sh"',
)
replace_once(
    "u-opti",
    'elif [[ "$FILE" = "smite.sh" || "$FILE" = "smite-install.sh" || "$FILE" = "smite-gateway.sh" || "$FILE" = "smite-foreign-gateway.sh" ]]; then',
    'elif [[ "$FILE" = "smite.sh" || "$FILE" = "smite-install.sh" || "$FILE" = "smite-gateway.sh" || "$FILE" = "smite-foreign-gateway.sh" || "$FILE" = "docker-3xui-certificate-multi.sh" ]]; then',
)
replace_once("u-opti", '-ne 25 ]; then', '-ne 26 ]; then')

# Mark the tested module as production-ready.
replace_once(
    "modules/docker-3xui-certificate-multi.sh",
    '# Experimental feature module for v0.15.1+',
    '# Production feature module for v0.15.2+',
)
replace_once(
    "modules/docker-3xui-certificate-multi.sh",
    '# Override Certificate Management after certificate.sh has been loaded.\n# Options 1-5 retain their existing behavior; option 6 becomes Instance-aware.',
    '# Production Certificate Management entry point loaded after the Multi-Instance registry.\n# Options 1-5 retain their existing behavior; option 6 becomes Instance-aware.',
)

# Harden renewal activation: validate hostname + key pairing before replacing the live copy.
replace_once(
    "modules/docker-3xui-certificate-multi.sh",
    'chown root:root "\\$TMP_CERT" "\\$TMP_KEY"\nmv -f "\\$TMP_CERT" "\\$TARGET_DIR/fullchain.pem"',
    'chown root:root "\\$TMP_CERT" "\\$TMP_KEY"\nopenssl x509 -in "\\$TMP_CERT" -noout -checkhost "\\$SELECTED_DOMAIN" >/dev/null 2>&1 || exit 1\nCERT_FP="\\$(openssl x509 -in "\\$TMP_CERT" -pubkey -noout 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | awk \'{print $1}\')"\nKEY_FP="\\$(openssl pkey -in "\\$TMP_KEY" -pubout -outform DER 2>/dev/null | sha256sum | awk \'{print $1}\')"\n[[ -n "\\$CERT_FP" && "\\$CERT_FP" == "\\$KEY_FP" ]] || exit 1\nmv -f "\\$TMP_CERT" "\\$TARGET_DIR/fullchain.pem"',
)

# Release metadata.
Path("VERSION").write_text("0.15.2\n")
replace_once("README.md", "**v0.15.1**", "**v0.15.2**")
replace_once(
    "README.md",
    "## Highlights in v0.15.1",
    "## Highlights in v0.15.2\n\n"
    "- Added production Multi-Instance TLS certificate synchronization for Sanaei 3x-UI Docker instances.\n"
    "- Certificate Management can select `3xui-01`, `3xui-02`, and later instances from the registry, reuse the instance domain's existing Let's Encrypt certificate, and expose it to Xray as `/root/cert/fullchain.pem` and `/root/cert/privkey.pem`.\n"
    "- Added certificate hostname/private-key validation, exact `/root/cert` bind-mount verification, atomic file synchronization, and container-side verification.\n"
    "- Added a per-instance Certbot deploy hook that synchronizes renewed certificates and restarts only the affected 3x-UI container.\n"
    "- Validated TLS end to end through the Smite gateway-first path with the client connecting to the Iran TCP/443 address while Xray terminates TLS on KH using the KH certificate/SNI.\n\n"
    "## Highlights in v0.15.1",
)
replace_once("CATALOG.md", "Current stable version: **v0.15.1**", "Current stable version: **v0.15.2**")
replace_once(
    "CATALOG.md",
    "- Nginx validation before reload.\n",
    "- Nginx validation before reload.\n"
    "- Sanaei 3x-UI Docker Multi-Instance certificate sync into each instance's `/root/cert` mount.\n"
    "- Per-instance Certbot deploy hooks for automatic renewal synchronization and targeted container restart.\n"
    "- Certificate/domain/private-key, bind-mount, source-copy, and container readability verification.\n",
)
changelog = Path("CHANGELOG.md").read_text()
marker = "## [0.15.1] - 2026-10-05\n"
section = """## [0.15.2] - 2026-10-05

### Added

- Added production Sanaei 3x-UI Docker Multi-Instance TLS certificate synchronization under Certificate Management option 6.
- Added registered Instance selection with domain/container/runtime status for `3xui-01`, `3xui-02`, and later instances.
- Added per-Instance Certbot deploy hooks that re-sync renewed certificates and restart only the affected container.

### Changed

- 3x-UI Docker TLS certificate management now uses `/opt/3x-ui/instances/<ID>/cert/` on the host and `/root/cert/` inside the selected container instead of assuming the legacy single-container layout.
- The existing legacy `3xui` certificate workflow remains available when no Multi-Instance registry exists.
- The U-OPTI installer and self-updater now package and validate the Multi-Instance certificate module.

### Security

- Certificate sync validates the certificate hostname and matching private key before activation.
- U-OPTI verifies that `/root/cert` is bound from the exact selected Instance directory before copying certificate material.
- Certificate and key files are replaced atomically, the private key remains mode `0600`, and renewed material is validated before the deploy hook activates it.

### Validation

- Live KH/Foreign testing passed for Instance `01` using an existing valid Let's Encrypt certificate.
- Host copy, container-visible files, certificate/key matching, current Let's Encrypt source matching, and the renewal deploy hook all passed verification.
- A VLESS/XHTTP inbound bound to loopback successfully used `/root/cert/fullchain.pem` and `/root/cert/privkey.pem` with TLS end to end through the Iran TCP/443 Smite/Backhaul path.

"""
if marker not in changelog:
    raise SystemExit("0.15.1 changelog marker not found")
Path("CHANGELOG.md").write_text(changelog.replace(marker, section + marker, 1))

# Extend CI so packaging regressions are caught.
ci = Path(".github/workflows/ci.yml").read_text()
ci_anchor = "          grep -Fq 'docker_smite_ensure_private_network_modules()' modules/docker.sh\n"
ci_extra = """

      - name: Validate 3x-UI Multi-Instance certificate packaging
        shell: bash
        run: |
          set -euo pipefail
          grep -Fq '\"docker-3xui-certificate-multi.sh\"' install.sh
          grep -Fq 'source \"$MODULES_PATH/docker-3xui-certificate-multi.sh\"' u-opti
          grep -Fq '\"docker-3xui-certificate-multi.sh\"' u-opti
          grep -Fq 'docker_3xui_multi_certificate_menu()' modules/docker-3xui-certificate-multi.sh
          grep -Fq 'docker_3xui_multi_cert_install_hook()' modules/docker-3xui-certificate-multi.sh
"""
if ci_anchor not in ci:
    raise SystemExit("CI anchor not found")
Path(".github/workflows/ci.yml").write_text(ci.replace(ci_anchor, ci_anchor + ci_extra, 1))

# Test-only bootstrap is retired now that normal install/update paths package the module.
Path("install-3xui-cert-test.sh").unlink(missing_ok=True)

# Remove this one-shot helper from the production commit.
Path(__file__).unlink(missing_ok=True)
