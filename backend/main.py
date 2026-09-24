from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import journal, live
from backend.engine import verdict
from backend.presentation import build_view
from backend.repository import ScenarioNotFound, list_scenarios, load_scenario
from backend.schemas import Event, Health, ScenarioListItem, View

log = logging.getLogger("daedalus")
JOURNAL_POLL_S = int(os.environ.get("JOURNAL_POLL_S", "20"))


def observe_live(tenant: str | None = None) -> dict:
    """Fetch, decide, word, and write to the journal whatever changed. One path for the endpoint and the watcher."""
    data = live.load_live(tenant)
    result = verdict(data)
    view = build_view(data, result, mode="live", journal=[])
    journal.observe(data["tenant"], view, at=data["now"])
    view["journal"] = journal.events(data["tenant"])
    return view


def _watch(stop: threading.Event) -> None:
    # The journal must not depend on somebody having the page open: a change at 03:00 is exactly the one
    # people want to read about at 09:00. The cache in live.py keeps this from doubling the load on the core.
    while not stop.is_set():
        try:
            observe_live()
        except live.LiveUnavailable as error:
            log.warning("journal watcher: %s", error)
        except Exception:
            log.exception("journal watcher failed")
        stop.wait(JOURNAL_POLL_S)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = threading.Event()
    if live.configured():
        threading.Thread(target=_watch, args=(stop,), name="journal-watcher", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Daedalus Infra Health", version="0.4.0", lifespan=lifespan)

# Read-only API with no credentials. Behind nginx the frontend is same-origin;
# the open CORS policy only matters for `npm run dev` against a local backend.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])


def _scenario_or_404(scenario_id: str) -> dict:
    try:
        return load_scenario(scenario_id)
    except ScenarioNotFound:
        raise HTTPException(status_code=404, detail="Scenario not found") from None


@app.get("/api/health", response_model=Health)
def health() -> dict:
    return {"status": "ok", "live": live.configured()}


@app.get("/api/scenarios", response_model=list[ScenarioListItem])
def scenarios() -> list[dict]:
    response = []
    for item in list_scenarios():
        data = load_scenario(item["id"])
        result = verdict(data)
        expected = data["expected"]
        response.append({
            **item,
            "actual": result["verdict"],
            "passed": result["verdict"] == expected["verdict"] and result["states"] == expected["states"],
        })
    return response


@app.get("/api/scenarios/{scenario_id}", response_model=View, response_model_exclude_none=True)
def scenario(scenario_id: str) -> dict:
    data = _scenario_or_404(scenario_id)
    return build_view(data, verdict(data), mode="demo")


@app.get("/api/scenarios/{scenario_id}/raw")
def scenario_raw(scenario_id: str) -> dict:
    """The mock Triage responses behind a scenario, exactly as the engine receives them."""
    return _scenario_or_404(scenario_id)


@app.get("/api/live", response_model=View, response_model_exclude_none=True)
def live_view(tenant: str | None = None) -> dict:
    """Same view model, computed from a real Triage core instead of a mock file."""
    try:
        return observe_live(tenant)
    except live.LiveUnavailable as error:
        raise HTTPException(status_code=503, detail=f"Live data unavailable: {error}") from None


@app.get("/api/live/journal", response_model=list[Event], response_model_exclude_none=True)
def live_journal(tenant: str | None = None, limit: int = 200) -> list[dict]:
    """Every recorded change for the live tenant, newest first."""
    name = tenant or os.environ.get("TRIAGE_TENANT")
    if not name:
        try:
            name = live.load_live(None)["tenant"]
        except live.LiveUnavailable as error:
            raise HTTPException(status_code=503, detail=f"Live data unavailable: {error}") from None
    return journal.events(name, limit=max(1, min(limit, 500)))
