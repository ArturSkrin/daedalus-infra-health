"""The agent mode of the shim: every container on the host is a target, found through the Docker API.

The daemon is faked at two levels: docker_source._get for the API rules, docker_source.discover for the collector.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from adapter import docker_source, shim
from adapter.collector import CYCLES_TO_OPEN, FORGET_AFTER_S, Collector
from adapter.config import Settings
from adapter.docker_source import Container
from backend.engine import verdict

CALM_CGROUP = {"cpuPressureAvg60": 0.1, "memPressureAvg60": 0.0, "ioPressureAvg60": 0.0,
               "memCurrentBytes": 100e6, "memMaxBytes": None, "oomKills": 0.0}


def up(name: str, tier: int = 2, **cgroup) -> Container:
    return Container(name, tier, True, "running", {**CALM_CGROUP, **cgroup})


# ------------------------------------------------------------ Docker API rules ---

def _api(containers: list[dict]):
    """A fake daemon: each item is (id, labels, inspect)."""
    def get(url, path, timeout):
        if path.startswith("/containers/json"):
            return [{"Id": c["Id"], "Labels": c.get("Labels", {})} for c in containers]
        return next(c["inspect"] for c in containers if path == f"/containers/{c['Id']}/json")
    return get


def _container(cid, service, status="running", project="shop", **extra):
    state = {"Status": status, **extra.pop("state", {})}
    host = {"RestartPolicy": {"Name": extra.pop("restart", "unless-stopped")}, "PortBindings": extra.pop("ports", {})}
    labels = {"com.docker.compose.project": project, "com.docker.compose.service": service, **extra.pop("labels", {})}
    return {"Id": cid, "Labels": labels, "inspect": {"Name": f"/{project}-{service}-1", "State": state, "HostConfig": host}}


def test_daemon_states_become_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_source, "_get", _api([
        _container("a1", "web", ports={"80/tcp": [{"HostPort": "80"}]}),
        _container("a2", "api", state={"Health": {"Status": "unhealthy"}}),
        _container("a3", "worker", "exited", state={"ExitCode": 137}),
        _container("a4", "migrate", "exited", state={"ExitCode": 0}, restart="no"),
        _container("a5", "cache", "restarting"),
        _container("a6", "debug", labels={"daedalus.ignore": "true"}),
        _container("a7", "api", labels={"com.docker.compose.oneoff": "True"}),
    ]))
    found = {c.name: c for c in docker_source.discover("unix:///x", str(tmp_path), 1)}
    assert set(found) == {"shop/web", "shop/api", "shop/worker", "shop/migrate", "shop/cache"}
    assert (found["shop/web"].ok, found["shop/web"].tier) == (True, 1)       # published port: the users' door
    assert (found["shop/api"].ok, found["shop/api"].tier) == (False, 2)
    assert found["shop/worker"].detail == "stopped (exit code 137)"
    assert found["shop/migrate"].ok                                            # a finished job is not a dead service
    assert not found["shop/cache"].ok


def test_a_failing_replica_speaks_for_its_service(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_source, "_get", _api([_container("b1", "api"), _container("b2", "api", "exited", state={"ExitCode": 1})]))
    (api,) = docker_source.discover("unix:///x", str(tmp_path), 1)
    assert not api.ok


def test_unreachable_daemon_is_none_not_an_empty_host(monkeypatch, tmp_path):
    def refuse(url, path, timeout):
        raise ConnectionRefusedError
    monkeypatch.setattr(docker_source, "_get", refuse)
    assert docker_source.discover("unix:///x", str(tmp_path), 1) is None


def test_cgroup_files_read_like_the_vitals_endpoint(tmp_path):
    (tmp_path / "cpu.pressure").write_text("some avg10=1.00 avg60=12.50 avg300=3.00 total=1\nfull avg10=0 avg60=0 avg300=0 total=0\n")
    (tmp_path / "memory.current").write_text("209715200\n")
    (tmp_path / "memory.max").write_text("max\n")
    (tmp_path / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 1\noom_kill 2\n")
    assert docker_source.read_cgroup(tmp_path) == {
        "cpuPressureAvg60": 12.5, "memPressureAvg60": None, "ioPressureAvg60": None,     # unreadable is not zero
        "memCurrentBytes": 209715200.0, "memMaxBytes": None, "oomKills": 2.0}


# ------------------------------------------------------------------ collector ---

@pytest.fixture
def host(monkeypatch, tmp_path):
    world = {"containers": [up("shop/web", tier=1), up("shop/api"), up("shop/db")]}
    clock = [1_790_000_000.0]
    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: world["containers"])
    settings = Settings(tenant="vps-1", cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path),
                        vitals_token=None, targets=(), discover=True)
    collector = Collector(settings, now=lambda: clock[0])

    def run(cycles=1):
        for _ in range(cycles):
            collector.cycle()
            clock[0] += settings.interval_s

    def decide() -> dict:
        return verdict({"tenant": "vps-1", "now": shim._iso(clock[0]), "status": shim.status(collector),
                        "incidents": shim.incidents(collector), "applications": shim.applications(collector),
                        "graph": shim.graph(collector), "analytics": shim.analytics(collector)})

    return world, collector, run, decide, clock


def test_a_healthy_host_needs_no_configuration(host):
    _, collector, run, decide, _ = host
    run(3)
    result = decide()
    assert result["verdict"] == "all_clear"
    assert result["states"]["trust"] == "full"                       # readiness and cgroup data for every container
    assert shim.status(collector)["tenantStats"]["tenants"]["vps-1"]["services"] == 3


def test_user_facing_container_down_is_act_now(host):
    world, collector, run, decide, _ = host
    run(2)
    world["containers"] = [Container("shop/web", 1, False, "stopped (exit code 1)", None), up("shop/api"), up("shop/db")]
    run(CYCLES_TO_OPEN)
    assert decide()["verdict"] == "act_now"
    (incident,) = shim.incidents(collector)["incidents"]
    assert incident["investigationPlan"][0] == "docker compose -p shop ps web"


def test_internal_container_down_is_scheduled_work(host):
    world, _, run, decide, _ = host
    run(2)
    world["containers"] = [up("shop/web", tier=1), up("shop/api"), Container("shop/db", 2, False, "restarting", None)]
    run(CYCLES_TO_OPEN + 4)                                          # long enough for probe errors to count, if they did
    assert (decide()["verdict"], decide()["trigger"]) == ("schedule", "warning_incident")


def test_a_removed_container_is_down_then_forgotten(host):
    world, collector, run, decide, clock = host
    run(2)
    world["containers"] = [up("shop/web", tier=1), up("shop/api")]          # shop/db removed
    run(CYCLES_TO_OPEN)
    assert collector.states["shop/db"].ready is False
    assert any(i["service"] == "shop/db" and i["status"] == "open" for i in shim.incidents(collector)["incidents"])
    clock[0] += FORGET_AFTER_S
    run(1)
    assert "shop/db" not in collector.states
    assert all(i["status"] == "resolved" for i in shim.incidents(collector)["incidents"])
    assert decide()["verdict"] == "all_clear"


def test_new_containers_join_without_a_restart(host):
    world, collector, run, _, _ = host
    run(1)
    world["containers"] = [*world["containers"], up("blog/web", tier=1)]
    run(1)
    assert collector.states["blog/web"].ready is True


def test_a_silent_daemon_is_blind_not_an_outage(host, monkeypatch):
    _, collector, run, decide, _ = host
    run(2)
    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: None)
    run(CYCLES_TO_OPEN + 1)
    assert decide()["verdict"] == "blind"
    assert shim.incidents(collector)["incidents"] == []


def test_memory_pressure_in_a_container_cgroup_is_brewing(host):
    world, _, run, decide, _ = host
    world["containers"] = [up("shop/web", tier=1), up("shop/api", memPressureAvg60=30.0, memCurrentBytes=480e6, memMaxBytes=512e6),
                           up("shop/db")]
    run(2)
    assert decide()["states"]["forecast"] == "brewing"


def test_discovered_containers_survive_an_agent_restart(host):
    world, collector, run, _, clock = host
    run(2)
    world["containers"] = [up("shop/web", tier=1), up("shop/api")]
    reborn = Collector(replace(collector.settings, targets=()), now=lambda: clock[0])
    reborn.cycle()
    assert reborn.states["shop/db"].ready is False                   # remembered from the state file, not dark
