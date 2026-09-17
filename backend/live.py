"""Read a real Triage core and shape it like a scenario bundle.

The engine does not care where a bundle comes from. Demo mode loads it from
mock_data/*.json; live mode assembles the same five blocks from the five
endpoints in the metrics catalog. Configure with environment variables:

    TRIAGE_BASE_URL   e.g. https://triage.example.com   (required for live mode)
    TRIAGE_TOKEN      bearer token, optional
    TRIAGE_TENANT     default tenant when the request names none
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TIMEOUT_S = 8


class LiveUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("TRIAGE_BASE_URL"))


def _get(path: str, tenant: str | None = None):
    base = os.environ.get("TRIAGE_BASE_URL", "").rstrip("/")
    if not base:
        raise LiveUnavailable("TRIAGE_BASE_URL is not set")
    url = base + path + (f"?tenant={urllib.parse.quote(tenant)}" if tenant else "")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get("TRIAGE_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # network, auth, bad JSON: all mean "no live data"
        raise LiveUnavailable(f"{path}: {error}") from error


def load_live(tenant: str | None = None) -> dict:
    tenant = tenant or os.environ.get("TRIAGE_TENANT")
    status = _get("/v2/agent/status")
    tenants = status.get("tenantStats", {}).get("tenants", {})
    if not tenant:
        if len(tenants) != 1:
            raise LiveUnavailable("name a tenant: " + ", ".join(sorted(tenants)) if tenants else "core reports no tenants")
        tenant = next(iter(tenants))

    # Catalog rule: read the tenant you asked for by name, never fall back to another.
    # A missing tenant is passed through as-is; the engine turns it into BLIND.
    applications = _get("/v2/agent/applications", tenant)
    incidents = _get("/v2/agent/incidents", tenant)
    return {
        "tenant": tenant,
        "now": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": status,
        "incidents": {"incidentMetrics": incidents.get("incidentMetrics", incidents), "incidents": incidents.get("incidents", [])},
        "applications": applications.get("applications", applications) if isinstance(applications, dict) else applications,
        "graph": _get("/v2/agent/graph", tenant),
        "analytics": _get("/v2/agent/analytics", tenant),
    }
