"""Read a real Triage core and shape it like a scenario bundle.

The engine does not care where a bundle comes from. Demo mode loads it from
mock_data/*.json; live mode assembles the same five blocks from the five
endpoints in the metrics catalog. bundle.normalize() absorbs whatever the core
omits, so this module only fetches. Configure with environment variables:

    TRIAGE_BASE_URL   e.g. https://triage.example.com   (one core or one agent)
    TRIAGE_TOKEN      bearer token, optional
    TRIAGE_TENANT     default tenant when the request names none
    AGENTS            a fleet instead: "vps-1=http://10.77.0.2:9000,vps-1-k3s=http://10.77.0.2:9001",
                      one Daedalus agent per tenant; the default view is all of them merged (tenant "fleet")
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from backend.fleet import FLEET, merge

log = logging.getLogger("daedalus.live")

TIMEOUT_S = 8
CACHE_TTL_S = 20          # every open tab polls each 30 s; the core is asked at most once per TTL per tenant
TENANT_ENDPOINTS = {
    "incidents": "/v2/agent/incidents",
    "applications": "/v2/agent/applications",
    "graph": "/v2/agent/graph",
    "analytics": "/v2/agent/analytics",
}

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


class LiveUnavailable(Exception):
    """Carries a message that is safe to show: no host names, no upstream error text."""


def agents() -> dict[str, str]:
    """tenant -> agent base URL, in the order AGENTS lists them."""
    pairs = (item.partition("=") for item in os.environ.get("AGENTS", "").split(",") if item.strip())
    return {name.strip(): url.strip().rstrip("/") for name, _, url in pairs}


def configured() -> bool:
    return bool(os.environ.get("TRIAGE_BASE_URL") or agents())


def tenants() -> list[str | None]:
    """Every tenant the watcher and /api/fleet look at. None: the single core's own default."""
    return list(agents()) or [os.environ.get("TRIAGE_TENANT") or None]


def _base(tenant: str | None) -> str:
    fleet = agents()
    if not fleet:
        return os.environ.get("TRIAGE_BASE_URL", "").rstrip("/")
    if tenant not in fleet:
        raise LiveUnavailable("no agent is configured for this tenant")
    return fleet[tenant]


def _get(path: str, tenant: str | None = None):
    base = _base(tenant)
    url = base + path + (f"?tenant={urllib.parse.quote(tenant)}" if tenant else "")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get("TRIAGE_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - URL comes from our own env
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:
        # The detail stays in the server log; the client learns only which endpoint failed.
        log.warning("Triage request failed: %s: %s", url, error)
        raise LiveUnavailable(f"the Triage core did not answer {path}") from error


def _fetch(tenant: str | None) -> dict:
    # a fleet has one agent per tenant, so even the status call is addressed by tenant (agents ignore the query)
    status = _get("/v2/agent/status", tenant if agents() else None)
    tenants = status.get("tenantStats", {}).get("tenants", {}) if isinstance(status, dict) else {}
    if not tenant:
        if len(tenants) != 1:
            raise LiveUnavailable("name a tenant with ?tenant=" if tenants else "the Triage core reports no tenants")
        tenant = next(iter(tenants))

    # Catalog rule: read the tenant you asked for by name and never fall back to another.
    # A tenant the core does not know is passed through; the engine turns it into BLIND.
    with ThreadPoolExecutor(max_workers=len(TENANT_ENDPOINTS)) as pool:
        futures = {name: pool.submit(_get, path, tenant) for name, path in TENANT_ENDPOINTS.items()}
        blocks = {name: future.result() for name, future in futures.items()}

    return {"tenant": tenant, "now": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
            "status": status, **blocks}


def _or_none(host: str) -> dict | None:
    try:
        return load_live(host)
    except LiveUnavailable:
        return None


def load_live(tenant: str | None = None) -> dict:
    if not configured():
        raise LiveUnavailable("live mode is not configured")
    hosts = agents()
    if hosts and tenant in (None, FLEET):
        # in parallel: a silent host costs one timeout, not one timeout per host in a row
        with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
            raws = dict(zip(hosts, pool.map(_or_none, hosts), strict=True))
        return merge(raws, datetime.now(UTC).astimezone().isoformat(timespec="seconds"))
    tenant = tenant or os.environ.get("TRIAGE_TENANT") or None
    key = tenant or ""
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    data = _fetch(tenant)
    with _lock:
        _cache[key] = (time.monotonic(), data)
    return data
