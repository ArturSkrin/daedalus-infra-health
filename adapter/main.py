"""HTTP face of the shim: the five /v2/agent/* endpoints of a Triage core, plus two for humans.

    uvicorn adapter.main:app --host 0.0.0.0 --port 9000
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from adapter import config, shim
from adapter.collector import Collector

log = logging.getLogger("daedalus.adapter")
collector = Collector(config.load())


def _loop(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            collector.cycle()
        except Exception:
            log.exception("collection cycle failed")      # one bad cycle must not end the loop
        stop.wait(collector.settings.interval_s)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="collector", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Daedalus compose shim", version="0.1.0", lifespan=lifespan)


def _ours(tenant: str | None) -> bool:
    return tenant in (None, "", collector.settings.tenant)


@app.get("/v2/agent/status")
def status() -> dict:
    return shim.status(collector)


@app.get("/v2/agent/incidents")
def incidents(tenant: str | None = None) -> dict:
    return shim.incidents(collector) if _ours(tenant) else {"incidents": [], "incidentMetrics": {}}


@app.get("/v2/agent/applications")
def applications(tenant: str | None = None) -> list[dict]:
    return shim.applications(collector) if _ours(tenant) else []


@app.get("/v2/agent/graph")
def graph(tenant: str | None = None) -> dict:
    return shim.graph(collector) if _ours(tenant) else {"nodes": [], "edges": []}


@app.get("/v2/agent/analytics")
def analytics(tenant: str | None = None) -> dict:
    return shim.analytics(collector) if _ours(tenant) else {}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "tenant": collector.settings.tenant, "lastCycleUnix": collector.last_cycle_at}


@app.get("/debug/targets")
def debug_targets() -> list[dict]:
    return shim.debug(collector)
