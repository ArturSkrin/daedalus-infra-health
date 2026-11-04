"""The host itself as two more targets next to its containers: its root disk and its memory. Never raises.

A full disk is the classic way a healthy-looking host stops (databases first), and no container reports it.
The thresholds make the target the verdict needs: at WARN it is a tier-2 service that is down (SCHEDULE),
at CRITICAL a tier-1 one (ACT NOW). Memory also lends its pressure (PSI) to the forecast, like a container's cgroup.
"""
from __future__ import annotations

import os
from pathlib import Path

from adapter.docker_source import Container, _avg60, _read

WARN_PCT, CRITICAL_PCT = 90.0, 97.0


def _target(name: str, used_pct: float, detail: str, cgroup: dict | None = None) -> Container:
    tier = 1 if used_pct >= CRITICAL_PCT else 2
    return Container(name, tier, used_pct < WARN_PCT, detail, cgroup)


def read(disk_path: str, proc: str = "/proc") -> list[Container]:
    found = []
    try:
        # disk_path is any path on the host's root filesystem mounted into the agent (/etc/hostname is enough):
        # statvfs reports the whole filesystem, and the agent sees no host files beyond that one.
        st = os.statvfs(disk_path)
        total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
        if total:
            used = 100 * (1 - free / total)
            found.append(_target("host/disk", used, f"{used:.0f}% used, {free / 1e9:.1f} GB free"))
    except OSError:
        pass                                    # not mounted: no disk target rather than a made-up one

    info = {}
    for line in (_read(Path(proc), "meminfo") or "").splitlines():
        key, _, value = line.partition(":")
        if value.strip().split(" ")[0].isdigit():
            info[key] = int(value.strip().split(" ")[0]) * 1024
    total, available = info.get("MemTotal"), info.get("MemAvailable")
    if total and available is not None:
        used = 100 * (1 - available / total)    # page cache counts as available: this is memory nobody can get back
        pressure = Path(proc) / "pressure"
        cgroup = {"cpuPressureAvg60": _avg60(_read(pressure, "cpu")), "memPressureAvg60": _avg60(_read(pressure, "memory")),
                  "ioPressureAvg60": _avg60(_read(pressure, "io")),
                  "memCurrentBytes": float(total - available), "memMaxBytes": float(total), "oomKills": None}
        found.append(_target("host/memory", used, f"{used:.0f}% used, {available / 1e9:.1f} GB available", cgroup))
    return found
