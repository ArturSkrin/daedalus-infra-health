from __future__ import annotations

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.engine import verdict
from backend.presentation import build_view
from backend.repository import (
    ScenarioNotFound,
    list_scenarios,
    load_scenario,
)


app = FastAPI(
    title="Daedalus Infra Health",
    version="0.1.0",
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
    }


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    response = []

    for item in list_scenarios():
        data = load_scenario(
            item["id"],
        )

        result = verdict(data)

        response.append(
            {
                **item,
                "actual": result["verdict"],
                "passed": (
                    result["verdict"]
                    == data["expected"]["verdict"]
                    and result["states"]
                    == data["expected"]["states"]
                ),
            }
        )

    return response


@app.get(
    "/api/scenarios/{scenario_id}"
)
def scenario(
    scenario_id: str,
) -> dict:
    try:
        data = load_scenario(
            scenario_id,
        )

    except ScenarioNotFound:
        raise HTTPException(
            status_code=404,
            detail="Scenario not found",
        )

    result = verdict(data)

    return build_view(
        data,
        result,
    )


@app.get(
    "/api/scenarios/{scenario_id}/raw"
)
def scenario_raw(
    scenario_id: str,
) -> dict:
    try:
        return load_scenario(
            scenario_id,
        )

    except ScenarioNotFound:
        raise HTTPException(
            status_code=404,
            detail="Scenario not found",
        )
