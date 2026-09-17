from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = ROOT / "mock_data"


class ScenarioNotFound(Exception):
    pass


def read_json(path: Path):
    return json.loads(
        path.read_text(
            encoding="utf-8",
        )
    )


def list_scenarios() -> list[dict]:
    return read_json(
        MOCK_DIR / "index.json",
    )


def scenario_index() -> dict[str, dict]:
    return {
        item["id"]: item
        for item in list_scenarios()
    }


def load_scenario(
    scenario_id: str,
) -> dict:
    index = scenario_index()

    item = index.get(
        scenario_id,
    )

    if item is None:
        raise ScenarioNotFound(
            scenario_id,
        )

    path = (
        MOCK_DIR
        / item["file"]
    )

    return read_json(path)
