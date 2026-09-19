from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

MOCK_DIR = Path(__file__).resolve().parents[1] / "mock_data"


def load(scenario_id: str) -> dict:
    return json.loads((MOCK_DIR / f"{scenario_id}.json").read_text(encoding="utf-8"))


@pytest.fixture
def calm() -> dict:
    """The quiet-morning bundle, free to mutate. No `expected` block: tests state their own."""
    data = copy.deepcopy(load("s01_calm"))
    data.pop("expected")
    return data


def tenant_of(data: dict) -> dict:
    return data["status"]["tenantStats"]["tenants"][data["tenant"]]


def app_of(data: dict, name: str) -> dict:
    return next(a for a in data["applications"] if a["name"] == name)
