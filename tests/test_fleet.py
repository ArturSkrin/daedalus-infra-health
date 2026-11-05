"""The tracker reading a fleet: one agent per tenant (AGENTS), one line per tenant on /api/fleet."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from adapter import docker_source, shim
from adapter.collector import Collector
from adapter.config import Settings
from adapter.docker_source import Container
from backend import acks, journal, live
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
    acks.reset()
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


def test_live_view_is_per_tenant_and_defaults_to_the_whole_fleet(fleet):
    assert fleet.get("/api/live", params={"tenant": "vps-b"}).json()["decision"]["verdict"] == "act_now"
    assert fleet.get("/api/live").json()["source"]["tenant"] == "fleet"
    assert fleet.get("/api/live", params={"tenant": "nobody"}).status_code == 503


def test_fleet_summary_judges_every_host_on_one_screen(fleet):
    view = fleet.get("/api/live").json()
    assert view["decision"]["verdict"] == "act_now"                     # a user-facing service is down on vps-b
    assert view["source"]["cluster"] == "3 hosts"
    users = next(i for i in view["indicators"] if i["id"] == "users")
    assert {r["service"] for r in users["drill"]["services"]} >= {"vps-a:shop/web", "vps-b:blog/web"}
    trust = next(i for i in view["indicators"] if i["id"] == "trust")
    assert "vps-c:agent" in {d["name"] for d in trust["drill"]["dark"]}  # the silent host is named, not hidden


def test_the_service_list_shows_every_host_with_the_broken_first(fleet):
    users = next(i for i in fleet.get("/api/live").json()["indicators"] if i["id"] == "users")
    rows = users["drill"]["services"]
    assert rows[0]["service"] == "vps-b:blog/web" and rows[0]["flag"] == "bad"


def test_a_silent_agent_is_asked_once_per_cache_ttl_not_on_every_page_load(fleet, monkeypatch):
    calls = []

    def silent(path, tenant=None):
        calls.append(path)
        raise live.LiveUnavailable("the Triage core did not answer " + path)

    monkeypatch.setattr(live, "_get", silent)
    for _ in range(3):
        with pytest.raises(live.LiveUnavailable):
            live.load_live("vps-c")
    assert calls == ["/v2/agent/status"]


def test_one_silent_host_among_healthy_ones_is_scheduled_work_not_blindness(monkeypatch, tmp_path):
    from backend.engine import verdict
    from backend.fleet import merge

    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: [
        Container(f"app{i}/web", 1, True, "running", CALM) for i in range(10)])
    settings = Settings(tenant="vps-a", cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path),
                        vitals_token=None, targets=(), discover="docker")
    agent = Collector(settings, now=time.time)
    for _ in range(3):
        agent.cycle()
    raw = {"tenant": "vps-a", **{path.rsplit("/", 1)[1]: block(agent) for path, block in SHIM.items()}}
    from backend.presentation import build_view

    data = merge({"vps-a": raw, "vps-c": None}, shim._iso(time.time()))
    result = verdict(data)
    assert (result["verdict"], result["states"]["trust"]) == ("schedule", "partial")
    trust = next(i for i in build_view(data, result, mode="live")["indicators"] if i["id"] == "trust")
    assert trust["caption"] == "vps-c:agent not answering"           # not "silent for 0 s": it never said when


def test_a_second_open_incident_is_named_under_the_reason_not_hidden_in_the_queue(monkeypatch, tmp_path):
    """Live on Backup: noise took the reason line and the real failure (job/file-backup) was visible only in a drill-in."""
    from backend.engine import verdict
    from backend.fleet import merge
    from backend.presentation import build_view

    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: [
        Container("job/file-backup", 2, False, "last run failed", None), Container("db/VCB", 2, False, "too small", None),
        Container("shop/web", 1, True, "running", CALM)])
    settings = Settings(tenant="Backup", cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path),
                        vitals_token=None, targets=(), discover="docker")
    agent = Collector(settings, now=time.time)
    for _ in range(3):
        agent.cycle()
    data = merge({"Backup": {"tenant": "Backup", **{p.rsplit("/", 1)[1]: block(agent) for p, block in SHIM.items()}}},
                 shim._iso(time.time()))
    decision = build_view(data, verdict(data), mode="live")["decision"]
    named = decision["reason"].split(":")[0] + ":" + decision["reason"].split(":")[1]
    assert decision["verdict"] == "schedule"
    assert sorted([named, *decision["alsoOpen"]]) == ["Backup:db/VCB", "Backup:job/file-backup"]


def test_each_tenant_keeps_its_own_journal(fleet):
    fleet.get("/api/fleet")
    assert fleet.get("/api/live/journal", params={"tenant": "vps-b"}).json()[0]["title"].startswith("Journal started: ACT")
    assert fleet.get("/api/live/journal", params={"tenant": "vps-a"}).json()[0]["kind"] == "started"


# --- acks: a human says "known, leave it" -----------------------------------------

def test_an_accepted_service_leaves_the_verdict_but_not_the_screen(fleet):
    assert fleet.get("/api/live").json()["decision"]["verdict"] == "act_now"
    ack = fleet.post("/api/acks", json={"service": "vps-b:blog/web", "days": 7, "reason": "fixing it on Saturday"}).json()
    assert (ack["kind"], ack["severity"]) == ("expected", "critical")
    view = fleet.get("/api/live").json()
    assert view["decision"]["verdict"] != "act_now"
    assert "vps-b:blog/web" not in {q["service"] for q in view["queue"]}
    assert [(a["service"], a["reason"]) for a in view["accepted"]] == [("vps-b:blog/web", "fixing it on Saturday")]
    assert view["journal"][0]["title"] == "Accepted as expected: vps-b:blog/web"
    # the host's own view names the service without the host, and the same ack holds there
    assert fleet.get("/api/live", params={"tenant": "vps-b"}).json()["accepted"][0]["service"] == "blog/web"

    assert fleet.delete("/api/acks/vps-b:blog/web").status_code == 204
    view = fleet.get("/api/live").json()
    assert view["decision"]["verdict"] == "act_now" and view["accepted"] == []
    assert any(e["title"] == "No longer accepted: vps-b:blog/web" for e in view["journal"])


def test_an_ack_needs_a_reason_and_a_window_of_at_most_30_days(fleet):
    assert fleet.post("/api/acks", json={"service": "vps-b:blog/web", "reason": ""}).status_code == 422
    assert fleet.post("/api/acks", json={"service": "vps-b:blog/web", "days": 31, "reason": "later"}).status_code == 422
    assert fleet.delete("/api/acks/vps-b:nothing").status_code == 404


def _raw(severity="warning", ready=False, status="open") -> dict:
    return {"tenant": "fleet", "incidents": {"incidents": [{"id": "b:1", "service": "b:web", "severity": severity, "status": status}],
                                             "incidentMetrics": {"criticalOpen": int(severity == "critical"),
                                                                 "warningOpen": int(severity == "warning")}},
            "applications": [{"name": "b:web", "ready": ready}]}


def test_an_ack_ends_with_its_window_when_it_gets_worse_and_after_a_day_of_health(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    acks.reset()
    acks.add("b:web", "expected", 1, "known", "warning", now=0)
    marked = acks.apply(_raw(), now=60)
    assert marked["incidents"]["incidents"][0]["status"] == "accepted"
    assert marked["incidents"]["incidentMetrics"]["warningOpen"] == 0
    assert acks.apply(_raw(), now=86_400)["incidents"]["incidents"][0]["status"] == "open"     # the window ran out

    acks.add("b:web", "expected", 7, "known", "warning", now=0)
    assert acks.apply(_raw("critical"), now=60)["incidents"]["incidents"][0]["status"] == "open"  # worse than accepted
    assert acks.listing() == []

    acks.add("b:web", "noise", 7, "flaky probe", "warning", now=0)
    acks.apply(_raw(ready=True, status="resolved"), now=3600)
    assert len(acks.listing()) == 1                         # fine for an hour proves nothing yet
    acks.apply(_raw(ready=True, status="resolved"), now=25 * 3600)
    assert acks.listing() == []                             # fine for a day: the problem is gone


def test_acks_survive_a_restart_of_the_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    acks.reset()
    acks.add("b:web", "expected", 7, "known", "warning")
    acks.reset()
    assert [a["service"] for a in acks.listing()] == ["b:web"]


# --- the admin screen -------------------------------------------------------------

def test_ops_lists_every_service_incident_and_agent_with_the_broken_first(fleet):
    fleet.post("/api/acks", json={"service": "vps-b:blog/web", "reason": "known"})
    data = fleet.get("/api/ops").json()
    first = data["services"][0]
    assert (first["host"], first["service"], first["ready"], first["accepted"]) == ("vps-b", "blog/web", False, "known")
    assert {(s["host"], s["service"]) for s in data["services"]} == {("vps-a", "shop/web"), ("vps-b", "blog/web")}
    assert [(i["host"], i["status"]) for i in data["incidents"]] == [("vps-b", "accepted")]
    agents = {a["host"]: a for a in data["agents"]}
    assert agents["vps-a"]["connected"] and not agents["vps-c"]["connected"]
    assert [a["service"] for a in data["acks"]] == ["vps-b:blog/web"]


def test_logs_try_the_service_then_its_unit_and_name_the_selector_that_answered(fleet, monkeypatch):
    from backend import logs

    asked = []
    monkeypatch.setenv("LOG_HOSTS", "vps-b=Backup")
    monkeypatch.setattr(logs, "_query", lambda selector, limit: asked.append(selector) or (
        [{"at": "t", "stream": "file-backup.service", "line": "Host key verification failed"}] if "unit" in selector else []))
    answer = fleet.get("/api/logs", params={"service": "vps-b:job/file-backup"}).json()
    assert asked == ['{host="Backup", service="job/file-backup"}', '{host="Backup", unit="file-backup.service"}']
    assert answer["selector"] == asked[1] and answer["lines"][0]["line"] == "Host key verification failed"
    assert fleet.get("/api/logs", params={"service": "no-host"}).status_code == 422


def test_logs_without_loki_say_so(fleet, monkeypatch):
    monkeypatch.delenv("LOKI_URL", raising=False)
    response = fleet.get("/api/logs", params={"service": "vps-a:shop/web"})
    assert response.status_code == 503 and "LOKI_URL" in response.json()["detail"]


def test_without_live_sources_the_fleet_is_empty(monkeypatch):
    monkeypatch.delenv("AGENTS", raising=False)
    monkeypatch.delenv("TRIAGE_BASE_URL", raising=False)
    assert TestClient(app).get("/api/fleet").json() == []
