"""Stand-in Triage core for exercising live mode without a real core or the EVE shim: serves one
scenario's own blocks over the same five /v2/agent/* endpoints a real core exposes.

    FAKE_TRIAGE_SCENARIO=s07_outage python mock_data/fake_triage.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent
SCENARIO = os.environ.get("FAKE_TRIAGE_SCENARIO", "s07_outage")
DATA = json.loads((ROOT / f"{SCENARIO}.json").read_text(encoding="utf-8"))

app = FastAPI(title="Fake Triage core")


@app.get("/v2/agent/status")
def status() -> dict:
    return DATA["status"]


@app.get("/v2/agent/incidents")
def incidents() -> dict:
    return DATA["incidents"]


@app.get("/v2/agent/applications")
def applications() -> list:
    return DATA["applications"]


@app.get("/v2/agent/graph")
def graph() -> dict:
    return DATA["graph"]


@app.get("/v2/agent/analytics")
def analytics() -> dict:
    return DATA["analytics"]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "scenario": SCENARIO}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9100)
