"""Stage26 inert KH Agent using Smite's genuine strict Agent router.

The FakeAdapters never open ports, run a tunnel, call Docker or change
firewall settings; only the HMAC middleware/routes are real.
"""
from fastapi import FastAPI
from app.routers.agent import router


class InertAdapter:
    def __init__(self):
        self.active_tunnels = {}
        self.calls = []

    async def apply_tunnel(self, *, tunnel_id, tunnel_core, spec):
        self.calls.append(("apply", tunnel_id))
        self.active_tunnels[tunnel_id] = (tunnel_core, spec)

    async def remove_tunnel(self, tunnel_id):
        self.calls.append(("remove", tunnel_id))
        self.active_tunnels.pop(tunnel_id, None)

    async def get_tunnel_status(self, tunnel_id):
        return {"running": tunnel_id in self.active_tunnels}


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.state.adapter_manager = InertAdapter()
app.include_router(router, prefix="/api/agent")


@app.get("/stage26-ready")
def ready():
    return {"ready": True}
