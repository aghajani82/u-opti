# Smite Stage 8 — Foreign Gateway authenticated self-check (DRAFT)

No live changes or merging. This change is stacked on the existing pairing
preview U-OPTI draft and coordinated with Smite Stage 8.

After a secure Node identity is staged in
`/etc/u-opti/smite/identities/node-identity.json` (root-owned 0600 under
private 0700 directory), U-OPTI uses a standard-library-only HMAC request
over validated HTTPS/443 to check ONLY this Node's own registration and
signed Panel->Node control readiness.

**No downgrade:** If identity exists, expired, malformed or unsafe, the
wizard refuses to silently fall back to anonymous `GET /api/nodes`.
If no identity exists on a legacy deployment, the old readiness check is
preserved for compatibility. Once Panel signed registration is enabled,
that legacy read requires admin JWT and is expected to fail without
successful pairing.

The new request is signed over exact bytes, method, path, timestamp, nonce,
and body digest; the identity secret is never in argv, query, logs or HTTP
response. It uses the default system CA and DNS checks and does not follow
redirects or environment proxies. The Panel replies with only a boolean
readiness value, never other Node identities or FRP tokens.

## Hold before testing on KH

- Smite Stage 8 default-off signed gateway-check must be built and deployed
  with the correct host main.py overlay and the paired Node DB.
- Stage 5 Node Agent strict and Stage 6 Panel signed calls must be
  activated together with matching persisted identity and durable replay DB.
- Node signed registration and FRP status, Panel public HTTPS/443,
  stable proxy path, Nginx allow-list and verified cert must all work.
- Pairing and secure file mounts into Smite Docker Node must be automated
  by the installer, then validated on disposable IR/KH snapshots.
- Standard mode only; leave Private Network mode as a separate rollout.

This PR does NOT by itself pair a Node or enable secure traffic.
