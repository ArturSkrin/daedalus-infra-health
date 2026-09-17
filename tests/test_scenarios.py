from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.engine import verdict


ROOT = Path(__file__).resolve().parents[1]
MOCK_DIR = ROOT / "mock_data"


INDEX = json.loads(
    (
        MOCK_DIR
        / "index.json"
    ).read_text(
        encoding="utf-8",
    )
)


@pytest.mark.parametrize(
    "scenario",
    INDEX,
    ids=lambda item: item["id"],
)
def test_scenario_matches_expected(
    scenario: dict,
):
    data = json.loads(
        (
            MOCK_DIR
            / scenario["file"]
        ).read_text(
            encoding="utf-8",
        )
    )

    result = verdict(data)

    assert (
        result["verdict"]
        == data["expected"]["verdict"]
    )

    assert (
        result["states"]
        == data["expected"]["states"]
    )


@pytest.mark.parametrize(
    "scenario",
    INDEX,
    ids=lambda item: item["id"],
)
def test_reason_line_matches_expected(
    scenario: dict,
):
    from backend.presentation import build_view

    data = json.loads(
        (
            MOCK_DIR
            / scenario["file"]
        ).read_text(
            encoding="utf-8",
        )
    )

    view = build_view(
        data,
        verdict(data),
    )

    assert (
        view["decision"]["reason"]
        == data["expected"]["reason"]
    )

    # exactly five indicators: the verdict plus four vitals
    assert len(view["indicators"]) == 4
