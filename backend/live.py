"""Read a real Triage core and shape it like a scenario bundle.

The engine does not care where a bundle comes from. Demo mode loads it from
mock_data/*.json; live mode assembles the same five blocks from the five
endpoints in the metrics catalog. bundle.normalize() absorbs whatever the core
omits, so this module only fetches. Configure with environment variables:

    TRIAGE_BASE_URL   e.g. https://triage.example.com   (required for live mode)
    TRIAGE_TOKEN      bearer token, optional
    TRIAGE_TENANT     default tenant when the request names none
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


def configured() -> bool:
    return bool(os.environ.get("TRIAGE_BASE_URL"))


def _get(path: str, tenant: str | None = None):
    base = os.environ.get("TRIAGE_BASE_URL", "").rstrip("/")
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
    status = _get("/v2/agent/status")
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


def load_live(tenant: str | None = None) -> dict:
    if not configured():
        raise LiveUnavailable("live mode is not configured")
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
