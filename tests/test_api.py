"""The HTTP surface: status codes, the response contract, and the live path against a fake core."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from backend import live
from backend.main import app
from backend.schemas import View
from tests.conftest import load

client = TestClient(app)


def test_health_reports_live_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("TRIAGE_BASE_URL", raising=False)
    assert client.get("/api/health").json() == {"status": "ok", "live": False}


def test_scenario_list_matches_every_expectation():
    items = client.get("/api/scenarios").json()
    assert len(items) == 11
    assert all(item["passed"] for item in items)


@pytest.mark.parametrize("scenario_id", [s["id"] for s in client.get("/api/scenarios").json()])
def test_every_scenario_view_honours_the_contract(scenario_id):
    response = client.get(f"/api/scenarios/{scenario_id}")
    assert response.status_code == 200
    view = View.model_validate(response.json())
    assert [i.id for i in view.indicators] == ["users", "forecast", "trust", "day"]
    assert sum(i.decides for i in view.indicators) <= 1
    assert sum(rule.fired for rule in view.decision.rules) == 1


def test_unknown_scenario_is_404_and_cannot_escape_the_folder():
    assert client.get("/api/scenarios/nope").status_code == 404
    assert client.get("/api/scenarios/..%2F..%2Fbackend%2Fmain").status_code == 404


def test_main_screen_carries_no_raw_values():
    """Raw numbers are allowed one level deep only. Everything outside `drill` is words."""
    view = client.get("/api/scenarios/s07_outage").json()
    surface = [view["decision"]["reason"], view["decision"]["word"]] + [i["caption"] + i["label"] for i in view["indicators"]]
    for raw_term in ("PSI", "p99", "errPct", "blast", "SLO", "MTTR", "0.62"):
        assert not any(raw_term.lower() in line.lower() for line in surface), raw_term


def test_live_is_503_when_not_configured(monkeypatch):
    monkeypatch.delenv("TRIAGE_BASE_URL", raising=False)
    response = client.get("/api/live")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.fixture
def fake_core(monkeypatch):
    """A Triage core served from a scenario file, with a request counter."""
    source = copy.deepcopy(load("s07_outage"))
    calls: list[str] = []

    def fake_get(path: str, tenant: str | None = None):
        calls.append(path)
        return {"/v2/agent/status": source["status"], "/v2/agent/incidents": source["incidents"],
                "/v2/agent/applications": source["applications"], "/v2/agent/graph": source["graph"],
                "/v2/agent/analytics": source["analytics"]}[path]

    monkeypatch.setenv("TRIAGE_BASE_URL", "https://triage.invalid")
    monkeypatch.setattr(live, "_get", fake_get)
    live._cache.clear()
    return calls


def test_live_view_is_built_by_the_same_engine(fake_core):
    view = client.get("/api/live").json()
    assert view["source"]["mode"] == "live"
    assert "scenario" not in view and "validation" not in view
    # applications carry unix stamps from the mock's own clock, long past by now: every block is stale
    assert view["decision"]["verdict"] in {"act_now", "blind"}


def test_live_answers_from_cache_within_the_ttl(fake_core):
    client.get("/api/live")
    first = len(fake_core)
    client.get("/api/live")
    assert first == 5 and len(fake_core) == first


def test_live_failure_does_not_leak_the_upstream_address(monkeypatch):
    monkeypatch.setenv("TRIAGE_BASE_URL", "http://127.0.0.1:9")     # nothing listens on the discard port
    live._cache.clear()
    response = client.get("/api/live")
    assert response.status_code == 503
    assert "127.0.0.1" not in response.text and "refused" not in response.text.lower()
