# Stage 12 — Inert KH Nginx/443 HMAC Agent location candidate

**DRAFT, no live service changes.** Follows the Stage 11 Overlay review
bundle and complements Smite Stage 12 trusted Node control origins.

In the current U-OPTI Standard Foreign Gateway, the hidden Nginx
location uses a `proxy_pass` URI ending in `/`. Nginx may replace
the incoming hidden prefix before forwarding it to Node. An HMAC-signed
request for `/api/agent/tunnels/apply` would then reach the application
with a different request target and must fail authentication.

The new `modules/smite-stage12-nginx-hmac-plan.py` generates a
**candidate only**, not a live Nginx site, for a narrowly scoped
`location ^~ /api/agent/` inside the existing KH TLS/443
server block. It uses:

- `allow` for loopback and one **explicit, confirmed IR Panel
  source IP**, then `deny all`.
- `limit_except GET POST` and `client_max_body_size 1m`.
- `proxy_pass http://127.0.0.1:8888;` with **no URI suffix**,
  preserving the exact Agent path/query for signature validation.
- The existing Node remains loopback-only. No new public listening
  port, no wildcard upstream, no secret-bearing URL or header.
- No Nginx file edits, reload, `nginx -t`, Docker commands or
  tunnel recreation. New output file must be inside a private
  service-user-owned mode-0700 directory and is created mode 0600.

**Never use the template as a complete Nginx configuration:** it
is a location *fragment*. Manual review is mandatory for existing
vhosts, TLS certificates, duplicate locations, trusted source IP
and conflicts with the old hidden gateway. Cloudflare-proxied
ingress, IPv6 path, asymmetric routing and Private Network mode
each require separate verification. Nginx source-IP ACLs alone
do not authenticate a Node; the signed Agent guard must also be active.

The companion Smite Stage 12 fixes an independent problem:
in signed mode the Panel can no longer take the destination
hostname from unauthenticated old Node metadata. Only a manually
approved, private per-Node origin is valid.

### Tests and release HOLD

`tests/test-smite-stage12-nginx-hmac-plan.py` tests path preservation,
source-IP validation, ACL ordering, no insecure URI rewrite, private
candidate permissions, no overwrite and no live mutations. This does
not prove the running Nginx or Docker process uses the intended
configuration.

**Do not enable strict/signed Panel↔Node modes or modify IR/KH yet.**
The two-host test needs image digest pinning, secret mounts, explicit
approved origins, signed ingress review and rollback confirmation
before real FRP, Backhaul and XHTTP traffic validation.
