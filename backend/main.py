from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import live
from backend.engine import verdict
from backend.presentation import build_view
from backend.repository import ScenarioNotFound, list_scenarios, load_scenario
from backend.schemas import Health, ScenarioListItem, View

app = FastAPI(title="Daedalus Infra Health", version="0.3.0")

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
        data = live.load_live(tenant)
    except live.LiveUnavailable as error:
        raise HTTPException(status_code=503, detail=f"Live data unavailable: {error}") from None
    return build_view(data, verdict(data), mode="live")
