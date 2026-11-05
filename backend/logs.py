"""Recent log lines of one service, read from Loki on the hub, for the admin screen.

    LOKI_URL    http://loki:3100 next to docker-compose.fleet-logs.yaml; unset: no logs
    LOG_HOSTS   "<tenant>=<host label>,...": the tracker names hosts after its agents (ccb-k3s), Loki after the
                inventory (CCB). A tenant not listed is its own label.

A tracker service is not always a Loki stream of the same name, so a few selectors are tried in order and the
first that has lines wins: the service itself; a systemd unit for job/<unit> (backup jobs live in the journal);
the whole namespace for a Kubernetes workload, since Loki names pods by container, not by Deployment.
The selector that answered is returned with the lines, so the person reading them knows what they are.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

TIMEOUT_S = 8
WINDOW_S = 6 * 3600


class LogsUnavailable(Exception):
    """Carries a message that is safe to show."""


def hosts() -> dict[str, str]:
    pairs = (item.partition("=") for item in os.environ.get("LOG_HOSTS", "").split(",") if item.strip())
    return {tenant.strip(): label.strip() for tenant, _, label in pairs}


def selectors(host: str, service: str, cluster: str | None) -> list[str]:
    label = json.dumps(hosts().get(host, host))          # a JSON string is a valid LogQL string
    tried = [f"{{host={label}, service={json.dumps(service)}}}"]
    if service.startswith("job/"):
        tried.append(f"{{host={label}, unit={json.dumps(service.removeprefix('job/') + '.service')}}}")
    if cluster == "k3s" and "/" in service:
        tried.append(f"{{host={label}, service=~{json.dumps(re.escape(service.split('/')[0]) + '/.*')}}}")
    return tried


def _query(selector: str, limit: int) -> list[dict]:
    base = os.environ.get("LOKI_URL", "").rstrip("/")
    if not base:
        raise LogsUnavailable("logs are not configured on this tracker (LOKI_URL)")
    params = urllib.parse.urlencode({"query": selector, "limit": limit, "direction": "backward",
                                     "start": int((time.time() - WINDOW_S) * 1e9)})
    try:
        with urllib.request.urlopen(f"{base}/loki/api/v1/query_range?{params}", timeout=TIMEOUT_S) as response:  # noqa: S310
            streams = json.loads(response.read())["data"]["result"]
    except Exception as error:
        raise LogsUnavailable("Loki did not answer") from error
    lines = [{"at": datetime.fromtimestamp(int(ts) / 1e9, UTC).astimezone().isoformat(timespec="seconds"),
              "ns": int(ts), "stream": s["stream"].get("service") or s["stream"].get("unit") or "", "line": line}
             for s in streams for ts, line in s.get("values") or []]
    lines.sort(key=lambda x: x["ns"], reverse=True)
    return [{k: v for k, v in x.items() if k != "ns"} for x in lines[:limit]]


def recent(host: str, service: str, cluster: str | None, limit: int = 200) -> dict:
    """Newest first. An empty answer still says which selectors were tried."""
    tried = selectors(host, service, cluster)
    for selector in tried:
        lines = _query(selector, limit)
        if lines:
            return {"selector": selector, "lines": lines}
    return {"selector": " or ".join(tried), "lines": []}
