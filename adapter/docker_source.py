"""Containers seen through the Docker Engine API, and their cgroup v2 files. Plain facts; never raises.

The agent reads the daemon instead of probing each service: every container on the host is found without
configuration, and a stopped or unhealthy one is seen even when nothing could reach it over the network.
Only GET /containers/* is used, so a docker-socket-proxy with CONTAINERS=1 is all the access it needs.
"""
from __future__ import annotations

import http.client
import json
import re
import socket
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

_cgroup_dirs: dict[str, Path] = {}      # container id -> its cgroup directory, found once


@dataclass(frozen=True)
class Container:
    name: str               # "<compose project>/<service>", or the container name outside compose
    tier: int
    ok: bool
    detail: str
    cgroup: dict | None


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._path)


def _get(url: str, path: str, timeout: float):
    """url is unix:///var/run/docker.sock or http://docker-proxy:2375."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "unix":
        connection = _UnixConnection(parsed.path, timeout)
    else:
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 2375, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise OSError(f"docker API {path}: HTTP {response.status}")
        return json.loads(body)
    finally:
        connection.close()


def _readiness(state: dict, restart_policy: str) -> tuple[bool, str]:
    status = state.get("Status")
    health = (state.get("Health") or {}).get("Status")
    if status == "running":
        if health == "unhealthy":
            return False, "running, but its healthcheck fails"
        return True, f"running ({health})" if health else "running"
    if state.get("OOMKilled"):
        return False, "killed: out of memory"
    if status == "exited":
        code = state.get("ExitCode")
        if code == 0 and restart_policy in ("", "no", "on-failure"):
            return True, "finished its job"         # a migration or a one-shot task, not a service that died
        return False, f"stopped (exit code {code})"
    return False, status or "unknown state"          # restarting, paused, created, dead


def _tier(info: dict, labels: dict) -> int:
    if (labels.get("daedalus.tier") or "").isdigit():
        return int(labels["daedalus.tier"])
    # a published port is the door users come in through; everything behind it is tier 2
    bindings = (info.get("HostConfig") or {}).get("PortBindings") or {}
    return 1 if any(bindings.values()) else 2


def _read(directory: Path, name: str) -> str | None:
    try:
        return (directory / name).read_text(encoding="utf-8")
    except OSError:
        return None


def _avg60(text: str | None) -> float | None:
    match = re.search(r"^some .*?avg60=([\d.]+)", text or "", re.M)
    return float(match.group(1)) if match else None


def read_cgroup(directory: Path) -> dict:
    """Same fields and meaning as integrations/eve-tools/vitals.ts: absent means not measured, never zero."""
    current = (_read(directory, "memory.current") or "").strip()
    maximum = (_read(directory, "memory.max") or "").strip()
    oom = re.search(r"^oom_kill (\d+)", _read(directory, "memory.events") or "", re.M)
    return {
        "cpuPressureAvg60": _avg60(_read(directory, "cpu.pressure")),
        "memPressureAvg60": _avg60(_read(directory, "memory.pressure")),
        "ioPressureAvg60": _avg60(_read(directory, "io.pressure")),
        "memCurrentBytes": float(current) if current.isdigit() and int(current) > 0 else None,
        "memMaxBytes": float(maximum) if maximum.isdigit() else None,      # "max": no limit, nothing to be close to
        "oomKills": float(oom.group(1)) if oom else None,
    }


def _cgroup_dir(root: Path, container_id: str) -> Path | None:
    if container_id in _cgroup_dirs:
        return _cgroup_dirs[container_id]
    # systemd driver, then cgroupfs; rootless Docker nests it under the user's slice, so walk for anything else
    candidates = [root / "system.slice" / f"docker-{container_id}.scope", root / "docker" / container_id]
    found = next((c for c in candidates if c.is_dir()), None)
    if found is None:
        try:
            found = next((p for p in root.rglob(f"*{container_id}*") if p.is_dir()), None)
        except OSError:
            found = None
    if found is not None:
        _cgroup_dirs[container_id] = found
    return found


def discover(url: str, cgroup_root: str, timeout: float) -> list[Container] | None:
    """Every container on the host. None when the daemon cannot be asked: that is blindness, not an empty host."""
    try:
        listed = _get(url, "/containers/json?all=true", timeout)
        found: dict[str, Container] = {}
        for item in listed:
            labels = item.get("Labels") or {}
            if labels.get("daedalus.ignore") == "true" or labels.get("com.docker.compose.oneoff") == "True":
                continue                            # opted out, or a `docker compose run` one-off
            info = _get(url, f"/containers/{urllib.parse.quote(item['Id'])}/json", timeout)
            project, service = labels.get("com.docker.compose.project"), labels.get("com.docker.compose.service")
            name = f"{project}/{service}" if project and service else (info.get("Name") or item["Id"][:12]).lstrip("/")
            state = info.get("State") or {}
            restart_policy = ((info.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or ""
            ok, detail = _readiness(state, restart_policy)
            directory = _cgroup_dir(Path(cgroup_root), item["Id"]) if state.get("Status") == "running" else None
            container = Container(name, _tier(info, labels), ok, detail, read_cgroup(directory) if directory else None)
            # replicas of one service share a name; the worst of them speaks for it
            if name not in found or (found[name].ok and not ok):
                found[name] = container
        return list(found.values())
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return None
