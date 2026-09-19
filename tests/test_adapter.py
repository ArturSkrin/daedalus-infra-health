"""The compose shim, judged by what the tracker finally says about the fleet it describes.

Network sources are faked; everything else is real: the collector accumulates, the shim renders the five
Triage responses, and the tracker's own engine turns them into a verdict.
"""
from __future__ import annotations

import pytest

from adapter import shim, sources
from adapter.collector import CYCLES_TO_OPEN, Collector
from adapter.config import EVE_PRESET, Settings, Target
from adapter.sources import Probe
from backend.engine import verdict
from backend.presentation import build_view

UP = Probe(True, True, 12.0, "HTTP 200")
BAD_GATEWAY = Probe(True, False, 8.0, "HTTP 502")
REFUSED = Probe(True, False, None, "ConnectionRefusedError")
NOT_ON_OUR_NETWORK = Probe(False, False, None, "name does not resolve on this network")


class Clock:
    def __init__(self):
        self.t = 1_790_000_000.0

    def __call__(self) -> float:
        return self.t


class World:
    """What the fake sources answer. Tests mutate it between cycles."""

    def __init__(self):
        self.probes = {"nginx": UP, "app": UP, "esi": UP}
        self.vitals: dict | None = self.make_vitals()

    @staticmethod
    def make_vitals(requests=0, errors=0, db_ok=True, **cgroup) -> dict:
        return {"ready": db_ok, "requests": requests, "errors": errors,
                "durationBucketsMs": {"100": requests, "1000": requests, "+Inf": requests},
                "deps": {"db": {"ok": db_ok, "ms": 3}},
                "cgroup": {"cpuPressureAvg60": 0.1, "memPressureAvg60": 0.0, "ioPressureAvg60": 0.0,
                           "memCurrentBytes": 200e6, "memMaxBytes": None, "oomKills": 0, **cgroup}}


@pytest.fixture
def rig(monkeypatch, tmp_path):
    world, clock = World(), Clock()
    by_url = {t["probe"]: t["name"] for t in EVE_PRESET if t.get("probe")}
    monkeypatch.setattr(sources, "http_probe", lambda url, timeout, headers=None: world.probes[by_url[url]])
    monkeypatch.setattr(sources, "fetch_vitals", lambda url, timeout, token: world.vitals)
    settings = Settings(tenant="eve-tools", cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path),
                        vitals_token=None, targets=tuple(Target(**{**t, "calls": tuple(t.get("calls", ()))}) for t in EVE_PRESET))
    collector = Collector(settings, now=clock)

    def run(cycles=1):
        for _ in range(cycles):
            collector.cycle()
            clock.t += settings.interval_s

    def decide() -> dict:
        data = {"tenant": "eve-tools", "now": shim._iso(clock.t), "status": shim.status(collector),
                "incidents": shim.incidents(collector), "applications": shim.applications(collector),
                "graph": shim.graph(collector), "analytics": shim.analytics(collector)}
        result = verdict(data)
        return {**result, "view": build_view(data, result, mode="live")}

    return world, collector, run, decide, settings, clock


def test_healthy_eve_is_all_clear_with_the_missing_history_named(rig):
    world, _, run, decide, *_ = rig
    run(4)
    result = decide()
    assert result["states"] == {"users": "ok", "forecast": "clear", "trust": "full", "day": "unknown"}
    assert (result["verdict"], result["trigger"]) == ("all_clear", "calm_unverified")
    assert "h of history" in result["view"]["decision"]["reason"]


def test_unpatched_eve_is_blind_not_green(rig):
    """Before EVE's app joins the shared network only nginx is visible: half the fleet. That is BLIND, honestly."""
    world, _, run, decide, *_ = rig
    world.probes["app"], world.vitals = NOT_ON_OUR_NETWORK, None
    run(3)
    result = decide()
    assert result["verdict"] == "blind"
    assert result["detail"]["trust"]["coverage"] == 50.0


def test_network_joined_but_no_vitals_asks_for_the_patch(rig):
    """Probes work, so users are judged; without cgroup data the forecast is blind, and that is work for a human."""
    world, _, run, decide, *_ = rig
    world.vitals = None
    run(3)
    result = decide()
    assert result["states"]["users"] == "ok"
    assert result["detail"]["trust"]["reasons"] == ["no_resource_data"]
    assert (result["verdict"], result["trigger"]) == ("schedule", "trust_partial")


def test_database_is_discovered_through_the_app_and_never_probed(rig):
    world, collector, run, _, *_ = rig
    world.vitals = None
    run(2)
    assert shim.status(collector)["tenantStats"]["tenants"]["eve-tools"]["services"] == 2      # nginx, app
    world.vitals = world.make_vitals()
    run(1)
    tenant = shim.status(collector)["tenantStats"]["tenants"]["eve-tools"]
    assert (tenant["services"], tenant["servicesDark"]) == (3, 0)                                # db joined the fleet
    assert "esi" not in [a["name"] for a in shim.applications(collector) if "reqPerSec" in a["golden"]]


def test_app_down_behind_nginx_is_act_now(rig):
    world, collector, run, decide, *_ = rig
    run(2)
    world.probes["nginx"], world.probes["app"], world.vitals = BAD_GATEWAY, REFUSED, None
    run(CYCLES_TO_OPEN)
    result = decide()
    assert result["verdict"] == "act_now"
    opened = [i for i in shim.incidents(collector)["incidents"] if i["status"] == "open"]
    assert {i["service"] for i in opened} == {"nginx", "app"}
    assert all(i["severity"] == "critical" for i in opened)


def test_a_container_we_saw_and_that_vanished_is_down_not_dark(rig):
    """A stopped container loses its DNS name. Never seen means dark; seen and gone means it stopped."""
    world, collector, run, decide, *_ = rig
    run(2)
    world.probes["nginx"], world.probes["app"], world.vitals = NOT_ON_OUR_NETWORK, NOT_ON_OUR_NETWORK, None   # compose down
    run(CYCLES_TO_OPEN)
    result = decide()
    assert (result["verdict"], result["trigger"]) == ("act_now", "users_broken")
    assert result["states"]["trust"] == "full"                       # we see exactly what happened
    assert "container stopped" in shim.incidents(collector)["incidents"][0]["title"]


def test_vanished_container_stays_down_across_a_collector_restart(rig):
    world, _, run, _, settings, clock = rig
    run(2)
    world.probes["app"], world.vitals = NOT_ON_OUR_NETWORK, None
    reborn = Collector(settings, now=clock)
    reborn.cycle()
    assert reborn.states["app"].ready is False                        # not "dark": the file remembers we had seen it


def test_database_down_breaks_the_app_and_opens_a_warning_for_db(rig):
    world, collector, run, decide, *_ = rig
    run(2)
    world.vitals = world.make_vitals(db_ok=False)
    run(CYCLES_TO_OPEN)
    result = decide()
    assert result["states"]["users"] == "broken"
    assert result["detail"]["users"]["service"] == "app"
    by_service = {i["service"]: i["severity"] for i in shim.incidents(collector)["incidents"]}
    assert by_service == {"app": "critical", "db": "warning"}


def test_recovery_closes_the_incident_as_auto_resolved(rig):
    world, collector, run, decide, *_ = rig
    run(1)
    world.probes["app"], world.vitals = REFUSED, None
    run(3)
    world.probes["app"], world.vitals = UP, world.make_vitals()
    run(3)
    incidents = shim.incidents(collector)
    assert incidents["incidentMetrics"]["criticalOpen"] == 0
    assert [i["resolvedBy"] for i in incidents["incidents"] if i["service"] == "app"] == ["agent"]
    assert decide()["verdict"] == "all_clear"


def test_third_party_outage_never_moves_the_verdict(rig):
    world, collector, run, decide, *_ = rig
    world.probes["esi"] = Probe(True, False, None, "TimeoutError")
    run(6)
    assert decide()["verdict"] == "all_clear"
    assert shim.incidents(collector)["incidents"] == []


def test_real_traffic_errors_reach_the_screen(rig):
    world, _, run, decide, *_ = rig
    run(1)                                                   # first vitals sample is only a baseline
    world.vitals = world.make_vitals(requests=400, errors=40)
    run(1)
    result = decide()
    assert result["states"]["users"] == "broken"             # 10 % on a user-path service
    assert 9 < result["detail"]["users"]["failingShare"] < 10


def test_first_vitals_sample_is_a_baseline_not_a_burst(rig):
    world, collector, run, _, *_ = rig
    world.vitals = world.make_vitals(requests=1_000_000, errors=900_000)     # totals since the app started
    run(1)
    rate = collector.rate("app")
    assert (rate["requests"], rate["errors"]) == (1.0, 0.0)                  # only our own probe


def test_counter_reset_after_app_restart_is_not_negative_traffic(rig):
    world, collector, run, _, *_ = rig
    world.vitals = world.make_vitals(requests=5000)
    run(1)
    world.vitals = world.make_vitals(requests=5200)
    run(1)
    world.vitals = world.make_vitals(requests=30)             # the app restarted
    run(1)
    assert collector.rate("app")["requests"] == 3 + 200 + 30  # three probes, then the deltas


def test_one_failed_request_in_a_quiet_minute_is_not_an_outage(rig):
    world, collector, run, decide, *_ = rig
    run(1)
    world.vitals = world.make_vitals(requests=4, errors=1)
    run(1)
    assert collector.rate("app")["errPct"] == 0.0            # under 3 errors and under 50 requests: noise
    assert decide()["verdict"] == "all_clear"
    world.vitals = world.make_vitals(requests=9, errors=3)
    run(1)
    assert collector.rate("app")["errPct"] > 0               # three real failures are worth showing


def test_cpu_stall_from_the_containers_own_cgroup_is_brewing(rig):
    world, _, run, decide, *_ = rig
    world.vitals = world.make_vitals(cpuPressureAvg60=35.0)
    run(2)
    result = decide()
    assert result["states"]["forecast"] == "brewing"
    assert result["detail"]["forecast"]["stalledResource"] == "CPU"
    assert result["verdict"] == "schedule"


def test_memory_share_is_reported_only_when_the_container_has_a_limit(rig):
    world, collector, run, _, *_ = rig
    run(1)
    assert "memReqPct" not in next(a for a in shim.applications(collector) if a["name"] == "app")["golden"]
    world.vitals = world.make_vitals(memCurrentBytes=460e6, memMaxBytes=512e6)
    run(1)
    assert next(a for a in shim.applications(collector) if a["name"] == "app")["golden"]["memReqPct"] == 89.8


def test_history_survives_a_collector_restart(rig):
    _, collector, run, _, settings, clock = rig
    run(30)
    buckets = len(shim.status(collector)["tenantStats"]["tenants"]["eve-tools"]["signalsHistory"])
    reborn = Collector(settings, now=clock)
    assert len(shim.status(reborn)["tenantStats"]["tenants"]["eve-tools"]["signalsHistory"]) == buckets >= 2


def test_shim_speaks_the_triage_api_over_http(rig, monkeypatch):
    """End to end: the tracker backend in live mode, pointed at the shim, with no code aware of the other."""
    from fastapi.testclient import TestClient

    from adapter import main as adapter_main
    from backend import live
    from backend.main import app as tracker

    _, collector, run, *_ = rig
    run(3)
    monkeypatch.setattr(adapter_main, "collector", collector)
    shim_client = TestClient(adapter_main.app)

    def through_http(path: str, tenant: str | None = None):
        response = shim_client.get(path, params={"tenant": tenant} if tenant else None)
        assert response.status_code == 200
        return response.json()

    monkeypatch.setenv("TRIAGE_BASE_URL", "http://collector:9000")
    monkeypatch.setenv("TRIAGE_TENANT", "eve-tools")
    monkeypatch.setattr(live, "_get", through_http)
    live._cache.clear()

    view = TestClient(tracker).get("/api/live").json()
    assert view["source"] == {**view["source"], "mode": "live", "tenant": "eve-tools", "cluster": "docker-compose"}
    assert [i["id"] for i in view["indicators"]] == ["users", "forecast", "trust", "day"]
    assert shim_client.get("/v2/agent/applications", params={"tenant": "someone-else"}).json() == []


def test_app_address_is_a_setting_because_eve_keeps_its_port_in_an_untracked_env_file(monkeypatch):
    from adapter import config

    monkeypatch.delenv("ADAPTER_TARGETS", raising=False)
    monkeypatch.setenv("EVE_APP_URL", "http://app:3000/")
    app = next(t for t in config.load().targets if t.name == "app")
    assert (app.probe, app.vitals) == ("http://app:3000/api/scan/progress", "http://app:3000/internal/vitals")

    monkeypatch.delenv("EVE_APP_URL")
    assert next(t for t in config.load().targets if t.name == "app").probe == "http://app:5000/api/scan/progress"
