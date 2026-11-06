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
import urllib.error
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


ERROR_LINE = "(?i)(error|fatal|panic|exception|traceback|fail)"


STATS_TIMEOUT_S = 30        # a day of every stream is a heavier question than one service's last lines


def _loki(path: str, params: dict) -> dict:
    base = os.environ.get("LOKI_URL", "").rstrip("/")
    if not base:
        raise LogsUnavailable("logs are not configured on this tracker (LOKI_URL)")
    try:
        with urllib.request.urlopen(f"{base}{path}?{urllib.parse.urlencode(params)}", timeout=STATS_TIMEOUT_S) as response:  # noqa: S310
            return json.loads(response.read())["data"]
    except urllib.error.HTTPError as error:
        # Loki says what it disliked in the body ("parse error", "query timed out"): an admin needs that, not a shrug
        detail = error.read().decode("utf-8", "replace").strip()[:200]
        raise LogsUnavailable(f"Loki refused the query (HTTP {error.code}): {detail}") from error
    except Exception as error:
        raise LogsUnavailable(f"Loki did not answer: {type(error).__name__}: {error}") from error


def activity(hours: int = 24, step_s: int = 600) -> dict:
    """Log lines and error lines of the whole fleet, one point per step: how busy the fleet was and how much of it
    went wrong. Until there is real request data (RED) this is the closest thing to traffic we have."""
    end = int(time.time()) // step_s * step_s
    start = end - hours * 3600 + step_s
    window = f"{step_s}s"

    def series(query: str) -> dict[int, float]:
        result = _loki("/loki/api/v1/query_range", {"query": query, "start": start, "end": end, "step": step_s}).get("result") or []
        return {int(float(t)): float(v) for t, v in (result[0].get("values") or [] if result else [])}

    lines = series(f'sum(count_over_time({{host=~".+"}}[{window}]))')
    errors = series(f'sum(count_over_time({{host=~".+"}} |~ "{ERROR_LINE}" [{window}]))')
    times = list(range(start, end + 1, step_s))
    return {"stepS": step_s, "start": start, "lines": [lines.get(t, 0.0) for t in times], "errors": [errors.get(t, 0.0) for t in times]}


def noisiest(limit: int = 12) -> list[dict]:
    """The streams that wrote the most error lines in the last hour, with their Loki labels."""
    query = f'topk({limit}, sum by (host, service) (count_over_time({{host=~".+"}} |~ "{ERROR_LINE}" [1h])))'
    result = _loki("/loki/api/v1/query", {"query": query}).get("result") or []
    rows = [{"host": r["metric"].get("host", ""), "service": r["metric"].get("service", ""), "errors": float(r["value"][1])}
            for r in result if r.get("metric")]
    return sorted((r for r in rows if r["errors"] > 0), key=lambda r: -r["errors"])


def stream(host_label: str, service_label: str, limit: int = 200) -> dict:
    """Lines of one Loki stream named by its own labels (as noisiest() returns them)."""
    selector = f"{{host={json.dumps(host_label)}, service={json.dumps(service_label)}}}"
    return {"selector": selector, "lines": _query(selector, limit)}


def recent(host: str, service: str, cluster: str | None, limit: int = 200) -> dict:
    """Newest first. An empty answer still says which selectors were tried."""
    tried = selectors(host, service, cluster)
    for selector in tried:
        lines = _query(selector, limit)
        if lines:
            return {"selector": selector, "lines": lines}
    return {"selector": " or ".join(tried), "lines": []}
