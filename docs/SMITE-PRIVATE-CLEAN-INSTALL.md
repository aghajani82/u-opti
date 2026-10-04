# Smite Private Network — Clean Install Path

This is the canonical clean-install order for the two-server U-OPTI Smite Private Network deployment.

Use this guide for the EasyTier-based Private Network flow. Do not mix it with the Standard/HTTPS Foreign Gateway flow.

## Roles

```text
IR / Panel server
- EasyTier: 10.89.10.10
- Smite Panel + Iran node
- Public Panel 443 Gateway

KH / Foreign server
- EasyTier: 10.89.10.20
- Sanaei 3x-UI
- Smite Foreign node
- Xray target on loopback
```

## Exact order

### 1. Both servers — install Docker

```text
U-OPTI Main Menu
7) Docker Management
1) Install Docker
```

### 2. KH — install Sanaei 3x-UI first

```text
U-OPTI Main Menu
7) Docker Management
4) 3x-UI Docker Management
-> Install 3x-UI in Docker
```

Use the KH domain and complete the managed Nginx + Let's Encrypt setup.

Do not use the Smite lifecycle shortcut for 3x-UI in this clean path.

### 3. KH — initialize EasyTier Foreign / KH

```text
U-OPTI Main Menu
7) Docker Management
5) Smite Management
2) EasyTier Private Network
2) Initialize Foreign / KH
```

Then:

```text
3) Show Pairing Details (Foreign)
```

Keep the generated pairing secret and hidden path private.

Expected overlay IP:

```text
10.89.10.20
```

### 4. IR — initialize EasyTier Panel / Iran

```text
U-OPTI Main Menu
7) Docker Management
5) Smite Management
2) EasyTier Private Network
4) Initialize Panel / Iran
```

Use the fresh pairing values from KH.

Expected overlay IP:

```text
10.89.10.10
```

Verify EasyTier connectivity before continuing.

### 5. IR — install Smite Panel + Iran Node

```text
U-OPTI Main Menu
7) Docker Management
5) Smite Management
1) Install Smite Components
1) Install Panel + Iran Node
```

Choose:

```text
Connection mode : Private Network
Private IPv4    : 10.89.10.10
```

### 6. KH — install Smite Foreign Node

```text
U-OPTI Main Menu
7) Docker Management
5) Smite Management
1) Install Smite Components
2) Install Foreign Node
```

Enter domains first, then select Private Network and use:

```text
Iran Panel Private IPv4 : 10.89.10.10
Foreign Private IPv4    : 10.89.10.20
```

Expected private control path:

```text
Panel -> Foreign Node: http://10.89.10.20:8888
```

## Important: no Foreign 443 Gateway in Private mode

Do **not** configure a Foreign HTTPS/443 Gateway on KH when `SMITE_CONNECTION_MODE=private`.

In Private Network mode:

```text
Foreign -> Panel     : 10.89.10.10:8000 over EasyTier
Panel -> Foreign API : 10.89.10.20:8888 over EasyTier
```

The U-OPTI menu blocks the Foreign HTTPS/443 Gateway in Private mode and directs the operator to the IR Panel Gateway step instead.

### 7. IR — configure the Panel 443 Gateway

```text
U-OPTI Main Menu
7) Docker Management
5) Smite Management
3) Panel 443 Gateway (Iran)
1) Configure / Repair Panel Gateway
```

This step is performed **before** creating the first Backhaul tunnel.

Expected gateway-first layout:

```text
Internet TCP/443
        |
        v
   Nginx stream
        |
        +-- Panel SNI -> 127.0.0.1:8443 -> Smite Panel
        |
        +-- default   -> 127.0.0.1:9443 -> future Backhaul data
```

Before Backhaul exists, no listener on `127.0.0.1:9443` is required. The address is reserved for the later Backhaul data listener.

Verify the Panel domain opens over HTTPS before continuing.

### 8. KH — create the Xray target

Create the Xray/VLESS inbound in 3x-UI and bind it to loopback, for example:

```text
Listen IP : 127.0.0.1
Port      : 10000
```

The port is only an example. Use any suitable free loopback port and point the Backhaul custom mapping to the same target.

### 9. Smite Panel — create Backhaul

Example:

```text
Iran Node      : node-ir
Foreign Node   : node-kh
Core           : Backhaul
Type           : TCP
Control Port   : 3080
Ports          : 443
Allow UDP      : Off
Custom Ports   : 443=127.0.0.1:10000
```

The UI keeps logical port `443`. With the Private Panel Gateway active, the runtime uses loopback `127.0.0.1:9443` for Backhaul data so Nginx remains the only public owner of TCP/443.

## Final validation

Verify:

```text
EasyTier IR <-> KH works
IR Panel domain opens over HTTPS/443
node-ir is active
node-kh is active
Panel -> KH API works over 10.89.10.20:8888
Xray target is loopback-only on KH
Backhaul tunnel is active
Client connects end-to-end
Public service exposure remains limited to TCP 80/443
```

Then reboot KH and validate again, followed by IR and another validation pass.
