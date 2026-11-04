"""host/disk and host/memory: the host as two targets next to its containers."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from adapter import docker_source, host_source, shim
from adapter.collector import CYCLES_TO_OPEN, Collector
from adapter.config import Settings
from backend.engine import verdict


def _proc(tmp_path, total_kb=8_000_000, available_kb=4_000_000, mem_psi="0.00"):
    (tmp_path / "pressure").mkdir()
    (tmp_path / "meminfo").write_text(f"MemTotal:       {total_kb} kB\nMemFree:  1 kB\nMemAvailable:   {available_kb} kB\n")
    (tmp_path / "pressure" / "memory").write_text(f"some avg10=0.00 avg60={mem_psi} avg300=0.00 total=0\n")
    (tmp_path / "pressure" / "cpu").write_text("some avg10=0.00 avg60=1.50 avg300=0.00 total=0\n")
    return str(tmp_path)


def _disk(monkeypatch, used_pct: float):
    blocks = 1000
    monkeypatch.setattr(os, "statvfs", lambda path: SimpleNamespace(f_blocks=blocks, f_frsize=1_000_000,
                                                                  f_bavail=int(blocks * (100 - used_pct) / 100)))


@pytest.mark.parametrize(("used", "ok", "tier"), [(50, True, 2), (92, False, 2), (98, False, 1)])
def test_disk_thresholds_become_readiness_and_tier(monkeypatch, tmp_path, used, ok, tier):
    _disk(monkeypatch, used)
    disk = next(t for t in host_source.read("/host/disk", _proc(tmp_path)) if t.name == "host/disk")
    assert (disk.ok, disk.tier) == (ok, tier)
    assert disk.detail.startswith(f"{used}% used")


def test_memory_counts_page_cache_as_available_and_lends_its_pressure(tmp_path):
    memory = next(t for t in host_source.read("/nowhere", _proc(tmp_path, available_kb=400_000, mem_psi="12.50"))
                  if t.name == "host/memory")
    assert (memory.ok, memory.tier) == (False, 2)                       # 95 % used
    assert memory.cgroup["memPressureAvg60"] == 12.5 and memory.cgroup["cpuPressureAvg60"] == 1.5
    assert memory.cgroup["memMaxBytes"] == 8_000_000 * 1024


def test_an_unmounted_disk_is_left_out_not_invented(tmp_path):
    assert [t.name for t in host_source.read(str(tmp_path / "missing"), _proc(tmp_path))] == ["host/memory"]


def test_a_filling_disk_schedules_and_a_full_one_acts_now(monkeypatch, tmp_path):
    calm = {"cpuPressureAvg60": 0.1, "memPressureAvg60": 0.0, "ioPressureAvg60": 0.0,
            "memCurrentBytes": 1e8, "memMaxBytes": None, "oomKills": 0.0}
    web = docker_source.Container("shop/web", 1, True, "running", calm)
    monkeypatch.setattr(docker_source, "discover", lambda url, root, timeout: [web])
    monkeypatch.setattr(host_source, "read", lambda path: [host_source._target("host/disk", state["used"], "disk")])
    state = {"used": 50.0}
    settings = Settings(tenant="vps-1", cluster="docker-compose", interval_s=15, timeout_s=1, data_dir=str(tmp_path),
                        vitals_token=None, targets=(), discover="docker", host_metrics=True)
    clock = [1_790_000_000.0]
    collector = Collector(settings, now=lambda: clock[0])

    def run(cycles):
        for _ in range(cycles):
            collector.cycle()
            clock[0] += 15

    def decide():
        return verdict({"tenant": "vps-1", "now": shim._iso(clock[0]), "status": shim.status(collector),
                        "incidents": shim.incidents(collector), "applications": shim.applications(collector),
                        "graph": shim.graph(collector), "analytics": shim.analytics(collector)})

    run(2)
    assert decide()["verdict"] == "all_clear"
    state["used"] = 93.0
    run(CYCLES_TO_OPEN)
    assert (decide()["verdict"], decide()["trigger"]) == ("schedule", "warning_incident")
    state["used"] = 98.0
    run(CYCLES_TO_OPEN)
    assert decide()["verdict"] == "act_now"
