"""Actual Smite auth/pairing routers in a disposable CI-only ASGI app."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from app.database import init_db, AsyncSessionLocal
from app.models import Admin
from app.routers import auth, node_pairing, signed_nodes
from app.config import settings
from app import node_pairing_store
from app.signed_node_registration import initialize_replay_schema

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await run_in_threadpool(node_pairing_store.initialize_schema, settings.db_path)
    await run_in_threadpool(initialize_replay_schema, settings.db_path)
    async with AsyncSessionLocal() as db:
        db.add(Admin(username="stage20-admin",
                     password_hash=auth.get_password_hash("stage20-disposable-secret")))
        await db.commit()
    yield

app = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None, redoc_url=None)
app.include_router(auth.router, prefix="/api/auth")
app.include_router(node_pairing.router, prefix="/api/node-pairing")
app.include_router(signed_nodes.router, prefix="/api/node-control")

@app.get("/api/status")
def status():
    return {"status":"ok","source":"actual-smite-pairing-routers"}
