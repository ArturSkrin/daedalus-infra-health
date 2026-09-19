"""Targets to watch. Override the preset with ADAPTER_TARGETS (a JSON list)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

# EVE Online Tools as deployed by its docker-compose.yaml: nginx -> app -> db, and the
# app depends on the public EVE ESI API. Host names are the compose service names, so
# the collector must share a Docker network with them (see docker-compose.eve.yaml).
EVE_PRESET = [
    {"name": "nginx", "tier": 1, "probe": "http://nginx/", "calls": ["app"]},
    {"name": "app", "tier": 1, "probe": "http://app:5000/api/scan/progress",
     "vitals": "http://app:5000/internal/vitals", "calls": ["db", "esi"]},
    # The database is not put on a shared network just to be probed. The app already knows whether its
    # database answers, and says so in its vitals: "via" reads db from there.
    {"name": "db", "tier": 2, "via": "app.db"},
    {"name": "esi", "tier": 3, "probe": "https://esi.evetech.net/latest/status/", "external": True},
]


@dataclass(frozen=True)
class Target:
    name: str
    tier: int = 2
    probe: str | None = None        # URL answered with < 500 means "ready"
    vitals: str | None = None       # in-app endpoint with real counters and cgroup pressure
    tcp: str | None = None          # host:port that must accept a connection
    via: str | None = None          # "<target>.<dependency>": readiness read from that target's vitals
    calls: tuple[str, ...] = ()
    external: bool = False          # a third-party dependency: probed less often, never opens an incident
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    tenant: str
    cluster: str
    interval_s: int
    timeout_s: float
    data_dir: str
    vitals_token: str | None
    targets: tuple[Target, ...]


def load() -> Settings:
    raw = os.environ.get("ADAPTER_TARGETS")
    items = json.loads(raw) if raw else EVE_PRESET
    targets = tuple(Target(name=i["name"], tier=int(i.get("tier", 2)), probe=i.get("probe"), vitals=i.get("vitals"),
                           tcp=i.get("tcp"), via=i.get("via"), calls=tuple(i.get("calls", ())), external=bool(i.get("external", False)),
                           headers=dict(i.get("headers", {}))) for i in items)
    return Settings(
        tenant=os.environ.get("ADAPTER_TENANT", "eve-tools"),
        cluster=os.environ.get("ADAPTER_CLUSTER", "docker-compose"),
        interval_s=int(os.environ.get("ADAPTER_INTERVAL_S", "15")),
        timeout_s=float(os.environ.get("ADAPTER_TIMEOUT_S", "4")),
        data_dir=os.environ.get("ADAPTER_DATA_DIR", "/data"),
        vitals_token=os.environ.get("VITALS_TOKEN") or None,
        targets=targets,
    )
