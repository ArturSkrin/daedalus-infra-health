"""Demo scenarios on disk. Files are parsed once and re-read only when they change."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = ROOT / "mock_data"


class ScenarioNotFound(Exception):
    pass


@lru_cache(maxsize=64)
def _parsed(path: Path, modified_ns: int):
    # modified_ns is part of the cache key: regenerating mock data invalidates the entry
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(path: Path):
    return _parsed(path, path.stat().st_mtime_ns)


def list_scenarios() -> list[dict]:
    return read_json(MOCK_DIR / "index.json")


def load_scenario(scenario_id: str) -> dict:
    # Looked up in the index, never joined into a path: an id cannot escape mock_data/.
    item = next((s for s in list_scenarios() if s["id"] == scenario_id), None)
    if item is None:
        raise ScenarioNotFound(scenario_id)
    return read_json(MOCK_DIR / item["file"])
