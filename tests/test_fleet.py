"""The tracker reading a fleet: one agent per tenant (AGENTS), one line per tenant on /api/fleet."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from adapter import docker_source, shim
from adapter.collector import Collector
from adapter.config import Settings
from adapter.docker_source import Container
from backend import journal, live
from backend.main import app

SHIM = {"/v2/agent/status": shim.status, "/v2/agent/incidents": shim.incidents, "/v2/agent/applications": shim.applications,
        "/v2/agent/graph": shim.graph, "/v2/agent/analytics": shim.analytics}
CALM = {"cpuPressureAvg60": 0.1, "memPressureAvg60": 0.0, "ioPressureAvg60": 0.0,
        "memCurrentBytes": 1e8, "memMaxBytes": None, "oomKills": 0.0}


@pytest.fixture
def fleet(monkeypatch, tmp_path):
    hosts = {"a": [Container("shop/web", 1, True, "running", CALM)],
             "b": [Container("blog/web", 1, False, "stopped (exit code 1)", None)]}
    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: hosts[root])
    agents = {}
    for tenant, root in (("vps-a", "a"), ("vps-b", "b")):
        settings = Settings(tenant=tenant, cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path / tenant),
                            vitals_token=None, targets=(), discover="docker", cgroup_root=root)
        agents[tenant] = Collector(settings, now=time.time)
        for _ in range(3):
            agents[tenant].cycle()

    def get(path, tenant=None):
        if tenant not in agents:
            raise live.LiveUnavailable("the Triage core did not answer " + path)
        return SHIM[path](agents[tenant])

    monkeypatch.setenv("AGENTS", "vps-a=http://10.77.0.1:9000, vps-b=http://10.77.0.2:9001/, vps-c=http://10.77.0.3:9000")
    monkeypatch.delenv("TRIAGE_BASE_URL", raising=False)
    monkeypatch.delenv("TRIAGE_TENANT", raising=False)
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(live, "_get", get)
    live._cache.clear()
    journal.reset()
    return TestClient(app)


def test_agents_setting_is_parsed_in_order():
    import os
    os.environ["AGENTS"] = "b=http://x:1/, a = http://y:2"
    try:
        assert live.agents() == {"b": "http://x:1", "a": "http://y:2"}
        assert live.tenants() == ["b", "a"]
    finally:
        del os.environ["AGENTS"]


def test_fleet_has_one_line_per_agent_and_a_silent_one_is_blind(fleet):
    items = {i["tenant"]: i for i in fleet.get("/api/fleet").json()}
    assert list(items) == ["vps-a", "vps-b", "vps-c"]
    assert items["vps-a"]["verdict"] in ("all_clear", "schedule")
    assert items["vps-b"]["verdict"] == "act_now"
    assert (items["vps-c"]["verdict"], items["vps-c"]["level"]) == ("blind", "bad")


def test_live_view_is_per_tenant_and_defaults_to_the_first(fleet):
    assert fleet.get("/api/live", params={"tenant": "vps-b"}).json()["decision"]["verdict"] == "act_now"
    assert fleet.get("/api/live").json()["source"]["tenant"] == "vps-a"
    assert fleet.get("/api/live", params={"tenant": "nobody"}).status_code == 503


def test_each_tenant_keeps_its_own_journal(fleet):
    fleet.get("/api/fleet")
    assert fleet.get("/api/live/journal", params={"tenant": "vps-b"}).json()[0]["title"].startswith("Journal started: ACT")
    assert fleet.get("/api/live/journal", params={"tenant": "vps-a"}).json()[0]["kind"] == "started"


def test_without_live_sources_the_fleet_is_empty(monkeypatch):
    monkeypatch.delenv("AGENTS", raising=False)
    monkeypatch.delenv("TRIAGE_BASE_URL", raising=False)
    assert TestClient(app).get("/api/fleet").json() == []
