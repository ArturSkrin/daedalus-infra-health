"""The admin screen (/ops): the fleet as raw tables, for the person who runs it.

The main screen words a decision for someone who only needs the word. This one shows what the agents report,
row by row, with no judgement on top: every service with its pressure and flags, every incident of the last day,
every agent and when it last spoke. Same data the verdict is made from, read through the same cache.
"""
from __future__ import annotations

from datetime import UTC, datetime

from backend import acks, live


def _iso(unix) -> str | None:
    return datetime.fromtimestamp(unix, UTC).astimezone().isoformat(timespec="seconds") if isinstance(unix, (int, float)) else None


def _agent_row(host: str, raw: dict | None, error: str | None) -> dict:
    if raw is None:
        return {"host": host, "connected": False, "cluster": None, "lastMessage": None, "services": 0, "dark": 0,
                "error": error or "did not answer"}
    stats = ((raw.get("status") or {}).get("clusterAgentStats") or {}).get(raw["tenant"]) or {}
    block = ((raw.get("status") or {}).get("tenantStats") or {}).get("tenants", {}).get(raw["tenant"]) or {}
    return {"host": host, "connected": bool(stats.get("connected")), "cluster": stats.get("cluster"),
            "lastMessage": _iso(stats.get("lastMessageUnix")), "services": int(block.get("services") or 0),
            "dark": int(block.get("servicesDark") or 0), "error": None if stats.get("connected") else "its source does not answer"}


def _live_hosts():
    for host in live.agents() or {None: ""}:
        try:
            yield host, live.load_live(host), None
        except live.LiveUnavailable as failure:
            yield host, None, str(failure)


def snapshot(scenario: dict | None = None) -> dict:
    """The live fleet, or one demo scenario as a fleet of one host (to look at the screen without agents)."""
    agents, services, incidents = [], [], []
    history: dict[str, list[float]] = {}            # bucket time -> [requests, errors], summed over the fleet
    hosts = [(scenario["tenant"], scenario, None)] if scenario else _live_hosts()
    for host, raw, error in hosts:
        name = host or (raw or {}).get("tenant") or "live"
        agents.append(_agent_row(name, raw, error))
        if raw is None:
            continue
        raw = acks.apply(raw, prefix=f"{name}:")
        nodes = (raw.get("graph") or {}).get("nodes") or []
        tiers = {n.get("name"): n.get("tier") for n in nodes}
        calls = {n.get("name"): [c for c in n.get("calls") or [] if isinstance(c, str)] for n in nodes}
        block_status = ((raw.get("status") or {}).get("tenantStats") or {}).get("tenants", {}).get(raw["tenant"]) or {}
        for bucket in block_status.get("signalsHistory") or []:
            if isinstance(bucket.get("t"), str):
                slot = history.setdefault(bucket["t"], [0.0, 0.0])
                slot[0] += bucket.get("requests") or 0
                slot[1] += bucket.get("requestErrors") or 0
        block = (raw.get("incidents") or {}).get("incidents") or []
        open_by_service = {i.get("service"): i for i in block if i.get("status") in ("open", "accepted")}
        cluster = agents[-1]["cluster"]
        for app in (a for a in raw.get("applications") or [] if isinstance(a.get("name"), str)):
            golden, incident = app.get("golden") or {}, open_by_service.get(app.get("name"))
            services.append({
                "host": name, "service": app.get("name"), "cluster": cluster, "ready": app.get("ready") is not False,
                "tier": tiers.get(app.get("name")), "cpuStallPct": golden.get("cpuPsiPct"), "memStallPct": golden.get("memPsiPct"),
                "ioStallPct": golden.get("ioPsiPct"), "memOfLimitPct": golden.get("memReqPct"), "oomKills": golden.get("oomKills"),
                "incident": incident.get("title") if incident else None, "severity": incident.get("severity") if incident else None,
                "flapping": app.get("flapping") is True, "accepted": (app.get("accepted") or {}).get("reason"),
                "calls": calls.get(app.get("name"), []),
            })
        dark = ((raw.get("status") or {}).get("tenantStats") or {}).get("tenants", {}).get(raw["tenant"], {}).get("darkServices") or []
        services += [{"host": name, "service": d["name"], "cluster": cluster, "ready": False, "dark": True}
                     for d in dark if isinstance(d.get("name"), str)]
        for i in block:
            incidents.append({
                "id": f"{name}:{i.get('id')}", "host": name, "service": i.get("service"), "severity": i.get("severity") or "warning",
                "status": i.get("status") or "open", "title": i.get("title") or "", "firstSeen": i.get("firstSeen"),
                "resolvedAt": i.get("resolvedAt"), "resolvedBy": i.get("resolvedBy"), "reopens": int(i.get("reopens") or 0),
                "accepted": (i.get("accepted") or {}).get("reason"),
            })
    services.sort(key=lambda s: (s["ready"], not s.get("incident"), s["host"], s["service"] or ""))
    order = {"open": 0, "accepted": 1, "resolved": 2}
    incidents.sort(key=lambda i: i["firstSeen"] or "", reverse=True)              # newest first within a group
    incidents.sort(key=lambda i: (order.get(i["status"], 3), i["severity"] != "critical"))
    return {"services": services, "incidents": incidents, "agents": agents, "acks": [acks.public(a) for a in acks.listing()],
            "history": [{"t": t, "requests": round(r, 1), "errors": round(e, 1)} for t, (r, e) in sorted(history.items())]}
