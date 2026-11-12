"""Containers seen through the Docker Engine API, and their cgroup v2 files. Plain facts; never raises.

The agent reads the daemon instead of probing each service: every container on the host is found without
configuration, and a stopped or unhealthy one is seen even when nothing could reach it over the network.
Only GET /containers/* is used, so a docker-socket-proxy with CONTAINERS=1 is all the access it needs.
"""
from __future__ import annotations

import http.client
import io
import json
import re
import socket
import tarfile
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

_cgroup_dirs: dict[str, Path] = {}      # container id -> its cgroup directory, found once
_sites: dict[str, tuple[float, tuple[str, ...]]] = {}  # nginx container id -> (read at, its public URLs)
SITES_EVERY_S = 600                     # a config changes with a deploy, and a deploy is a new container anyway


@dataclass(frozen=True)
class Container:
    name: str               # "<compose project>/<service>", or the container name outside compose
    tier: int
    ok: bool
    detail: str
    cgroup: dict | None
    calls: tuple[str, ...] = ()     # what it depends on, by the same names (compose depends_on, k8s Service DNS names)
    traffic: dict | None = None     # cumulative requests, 5xx and latency buckets the ingress saw for it (Traefik on k3s)
    urls: tuple[str, ...] = ()      # public addresses users reach it at: nginx server_name, k8s Ingress hosts


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
    return json.loads(_raw(url, path, timeout))


def _raw(url: str, path: str, timeout: float) -> bytes:
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
        return body
    finally:
        connection.close()


# The public names a site answers to, read from its nginx: compose projects keep nginx/default.conf in the project
# and mount it into an nginx container. Read through the Docker API (GET /containers/<id>/archive, allowed by the
# socket proxy with CONTAINERS=1), so the agent needs no host path and follows whatever the project mounts.
_SERVER_NAME = re.compile(r"^\s*server_name\s+([^;]+);", re.M)
_HOSTNAME = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def server_names(config: str) -> list[str]:
    """Real host names from nginx server_name lines: no _, localhost, wildcards, regexes or bare IPs."""
    names = []
    for line in _SERVER_NAME.findall(re.sub(r"#.*", "", config)):
        for name in line.split():
            name = name.lower().rstrip(".")
            if _HOSTNAME.match(name) and name not in names:
                names.append(name)
    return names


def _nginx_urls(url: str, container_id: str, timeout: float, now: float) -> tuple[str, ...]:
    hit = _sites.get(container_id)
    if hit and now - hit[0] < SITES_EVERY_S:
        return hit[1]
    found: list[str] = []
    for path in ("/etc/nginx/conf.d", "/etc/nginx/sites-enabled"):
        try:
            archive = _raw(url, f"/containers/{urllib.parse.quote(container_id)}/archive?path={urllib.parse.quote(path)}", timeout)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.size < 1_000_000:
                        text = (tar.extractfile(member) or io.BytesIO()).read().decode("utf-8", "replace")
                        found += [n for n in server_names(text) if n not in found]
        except (OSError, tarfile.TarError, http.client.HTTPException):
            continue                    # no such folder in this image
    urls = tuple(f"https://{name}/" for name in found)
    _sites[container_id] = (now, urls)
    return urls


def _readiness(state: dict, restart_policy: str) -> tuple[bool, str]:
    status = state.get("Status")
    health = (state.get("Health") or {}).get("Status")
    if status == "running":
        if health == "unhealthy":
            return False, "running, but its healthcheck fails"
        return True, f"running ({health})" if health else "running"
    if status == "created":
        # compose creates a container and starts it once its depends_on are healthy; during a deploy that is half a minute
        return True, "created, waiting to start"
    if state.get("OOMKilled"):
        return False, "killed: out of memory"
    if status == "exited":
        code = state.get("ExitCode")
        if code == 0 and restart_policy in ("", "no", "on-failure"):
            return True, "finished its job"         # a migration or a one-shot task, not a service that died
        return False, f"stopped (exit code {code})"
    return False, status or "unknown state"          # restarting, paused, dead


def _tier(info: dict, labels: dict) -> int:
    if (labels.get("daedalus.tier") or "").isdigit():
        return int(labels["daedalus.tier"])
    # a port published beyond loopback is the door users come in through; everything behind it is tier 2
    bindings = (info.get("HostConfig") or {}).get("PortBindings") or {}
    public = [b for host in bindings.values() for b in host or [] if b.get("HostIp") not in ("127.0.0.1", "::1")]
    return 1 if public else 2


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
            if (info.get("HostConfig") or {}).get("AutoRemove"):
                continue        # `docker run --rm`: a one-off task (a backup dump, a migration) that is gone when it is done
            project, service = labels.get("com.docker.compose.project"), labels.get("com.docker.compose.service")
            name = f"{project}/{service}" if project and service else (info.get("Name") or item["Id"][:12]).lstrip("/")
            state = info.get("State") or {}
            restart_policy = ((info.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name") or ""
            ok, detail = _readiness(state, restart_policy)
            directory = _cgroup_dir(Path(cgroup_root), item["Id"]) if state.get("Status") == "running" else None
            # compose writes depends_on into a label: "db:service_healthy:false,cache:service_started:false"
            depends = labels.get("com.docker.compose.depends_on") or ""
            calls = tuple(f"{project}/{d.split(':')[0]}" for d in depends.split(",") if d and project)
            image = (item.get("Image") or "").lower()
            urls = _nginx_urls(url, item["Id"], timeout, time.time()) \
                if state.get("Status") == "running" and ("nginx" in image or "openresty" in image) else ()
            container = Container(name, _tier(info, labels), ok, detail, read_cgroup(directory) if directory else None, calls,
                                  urls=urls)
            # replicas of one service share a name; the worst of them speaks for it
            if name not in found or (found[name].ok and not ok):
                found[name] = container if container.urls or name not in found else \
                    Container(**{**container.__dict__, "urls": found[name].urls})
        return list(found.values())
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        return None
