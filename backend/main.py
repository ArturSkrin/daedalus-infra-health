from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import live
from backend.engine import verdict
from backend.presentation import build_view
from backend.repository import (
    ScenarioNotFound,
    list_scenarios,
    load_scenario,
)


app = FastAPI(
    title="Daedalus Infra Health",
    version="0.2.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "live": live.configured(),
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    response = []

    for item in list_scenarios():
        data = load_scenario(item["id"])
        result = verdict(data)

        response.append(
            {
                **item,
                "actual": result["verdict"],
                "passed": (
                    result["verdict"] == data["expected"]["verdict"]
                    and result["states"] == data["expected"]["states"]
                ),
            }
        )

    return response


@app.get("/api/scenarios/{scenario_id}")
def scenario(scenario_id: str) -> dict:
    try:
        data = load_scenario(scenario_id)

    except ScenarioNotFound:
        raise HTTPException(
            status_code=404,
            detail="Scenario not found",
        )

    return build_view(data, verdict(data), mode="demo")


@app.get("/api/scenarios/{scenario_id}/raw")
def scenario_raw(scenario_id: str) -> dict:
    try:
        return load_scenario(scenario_id)

    except ScenarioNotFound:
        raise HTTPException(
            status_code=404,
            detail="Scenario not found",
        )


@app.get("/api/live")
def live_view(tenant: str | None = None) -> dict:
    """Same view model, computed from a real Triage core instead of a mock file."""
    try:
        data = live.load_live(tenant)

    except live.LiveUnavailable as error:
        raise HTTPException(
            status_code=503,
            detail=f"Live data unavailable: {error}",
        )

    return build_view(data, verdict(data), mode="live")
