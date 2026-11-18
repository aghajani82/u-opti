# RC9 retained Iran Panel upgrade

This trial upgrade adds Backhaul publishing from the existing Smite Panel.
It applies to an enrolled Iran RC9 installation with a working paired Node,
signed WSS and active FRP. Setup prepares Backhaul HTTPS ingress before opening
the publishing workflow. It checks any existing Backhaul routes.

After updating U-OPTI to the approved trial revision, select **Tunnel Wizard →
1) Backhaul → 1) Set up signed Backhaul, HTTPS/443 and Smite publishing** on Iran.
The wizard verifies or prepares the engine and ingress, then offers to enable
publishing. Run **1) Backhaul** on the Foreign host to prepare its engine and
ingress. An already active publisher is verified without recreating the Panel.

For standalone diagnostics, run the following preflight in a root terminal.
When Cosign is absent, the helper verifies a temporary copy of the pinned binary.

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-rc9-retained-panel.py plan
```

Proceed on `RETAINED_RC9_PANEL=READY`. The installation briefly restarts the
Panel. It takes a SQLite backup and applies an image-only Compose override
pinned to the signed release. It checks the local Node identity and tunnel
process continuity and probes the already-published Backhaul routes.

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-rc9-retained-panel.py apply
```

At the prompt enter `APPLY-RC9-PANEL-ONLY`. After
`RETAINED_RC9_PANEL=APPLIED`, reload the browser and use
**Tunnels → Create Tunnel → Backhaul**. Select the paired nodes and the dedicated
inbound port. The Panel obtains the XHTTP path from signed Node inventory.
Confirm the new connection and retest all existing connections with a real client.

The same helper recovers an interrupted upgrade or restores the prior Panel.
It retains the live database, including tunnel rows created after the upgrade.

```sh
python3 -B /usr/local/lib/u-opti/modules/smite-rc9-retained-panel.py rollback
```

Enter `ROLLBACK-RC9-PANEL-ONLY` when prompted. A `HOLD` result indicates which
precondition or recovery step failed.
