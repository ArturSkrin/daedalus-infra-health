"""The whole fleet as one tenant: every agent's five blocks merged into one raw bundle.

The engine and the screen do not change: they judge \"fleet\" the way they judge one host. Service names become
\"<host>:<service>\", so a drill-in or an incident still says where. A host whose agent does not answer, or whose
agent lost its own source (Docker daemon, Kubernetes API), counts as one dark service \"<host>:agent\": the
fleet's trust drops, but one silent host does not blind the rest.
"""
from __future__ import annotations

from datetime import datetime

FLEET = "fleet"


def _iso_key(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _block(raw: dict) -> dict:
    return ((raw.get("status") or {}).get("tenantStats") or {}).get("tenants", {}).get(raw["tenant"]) or {}


def _connected(raw: dict) -> bool:
    stats = (raw.get("status") or {}).get("clusterAgentStats") or {}
    return bool((stats.get(raw["tenant"]) or {}).get("connected"))


def merge(hosts: dict[str, dict | None], now: str) -> dict:
    """hosts: host -> raw bundle from live.load_live, or None when its agent did not answer."""
    def named(host: str, name):
        return f"{host}:{name}" if isinstance(name, str) else name

    apps, nodes, edges, incidents, dark, precursors = [], [], [], [], [], []
    services = dark_count = open_now = sampled = unmapped = critical = warning = 0
    history: dict[float, list] = {}
    last_message = 0
    for host, raw in hosts.items():
        if raw is None or not _connected(raw):
            services, dark_count = services + 1, dark_count + 1
            dark.append({"name": f"{host}:agent", "lastEventAt": None})
            continue
        block = _block(raw)
        services += int(block.get("services") or 0)
        dark_count += int(block.get("servicesDark") or 0)
        dark += [{**d, "name": named(host, d.get("name"))} for d in block.get("darkServices") or []]
        open_now += int((block.get("incidents") or {}).get("openNow") or 0)
        sampled += int(block.get("sampledIncidents") or 0)
        unmapped += int((raw.get("status") or {}).get("unmappedServices") or 0)
        for bucket in block.get("signalsHistory") or []:
            key = _iso_key(bucket.get("t"))
            if key is not None:
                slot = history.setdefault(key, [bucket.get("t"), 0.0, 0.0])
                slot[1] += bucket.get("requests") or 0
                slot[2] += bucket.get("requestErrors") or 0
        last_message = max(last_message, int((((raw["status"].get("clusterAgentStats") or {}).get(raw["tenant"]) or {})
                                               .get("lastMessageUnix")) or 0))

        apps += [{**a, "name": named(host, a.get("name"))} for a in raw.get("applications") or []]
        graph = raw.get("graph") or {}
        nodes += [{**n, "name": named(host, n.get("name")), "calls": [named(host, c) for c in n.get("calls") or []],
                   "calledBy": [named(host, c) for c in n.get("calledBy") or []]} for n in graph.get("nodes") or []]
        edges += [{"from": named(host, e.get("from")), "to": named(host, e.get("to"))} for e in graph.get("edges") or []]
        block_incidents = raw.get("incidents") or {}
        incidents += [{**i, "id": named(host, i.get("id")), "service": named(host, i.get("service"))}
                      for i in block_incidents.get("incidents") or []]
        metrics = block_incidents.get("incidentMetrics") or {}
        critical += int(metrics.get("criticalOpen") or 0)
        warning += int(metrics.get("warningOpen") or 0)
        precursors += [{**p, "service": named(host, p.get("service"))} for p in (raw.get("analytics") or {}).get("precursorMatches") or []]

    reachable = len(hosts) - sum(1 for d in dark if d["name"].endswith(":agent"))
    tenant = {
        "services": services, "servicesDark": dark_count, "darkServices": dark,
        "serviceCoveragePct": round(100 * (services - dark_count) / services, 1) if services else 0,
        "signalsHistory": [{"t": t, "requests": round(r, 1), "requestErrors": round(e, 1)} for _, (t, r, e) in sorted(history.items())],
        "incidents": {"openNow": open_now}, "sampledIncidents": sampled,
    }
    return {
        "tenant": FLEET, "now": now,
        "status": {"tenantStats": {"tenants": {FLEET: tenant}}, "unmappedServices": unmapped,
                   # the fleet is \"connected\" while any host speaks; silent hosts are dark services above
                   "clusterAgentStats": {FLEET: {"cluster": f"{len(hosts)} hosts", "connected": reachable > 0,
                                                 "lastMessageUnix": last_message or None}}},
        "incidents": {"tenant": FLEET, "incidents": incidents,
                      "incidentMetrics": {"criticalOpen": critical, "warningOpen": warning, "infoOpen": 0}},
        "applications": apps,
        "graph": {"tenant": FLEET, "nodes": nodes, "edges": edges},
        "analytics": {"tenant": FLEET, "baselines": [], "patterns": [], "precursorMatches": precursors},
    }
