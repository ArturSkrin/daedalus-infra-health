"""Render collector state as the five Triage responses the tracker reads.

Only fields the tracker's bundle.py understands are produced, under the names
from the metrics catalog. Whatever the shim cannot know is left out, not zeroed:
the engine treats a missing field as "not measured", which is the truth here.
"""
from __future__ import annotations

from datetime import UTC, datetime

from adapter.collector import BUCKET_S, Collector


def _iso(unix: float) -> str:
    return datetime.fromtimestamp(unix, UTC).astimezone().isoformat(timespec="seconds")


def _blast_radius(collector: Collector) -> dict[str, float]:
    """Share of the fleet that stops working when a service does: itself plus everything that calls it, transitively."""
    targets = collector.settings.targets
    callers: dict[str, set[str]] = {t.name: set() for t in targets}
    for target in targets:
        for callee in target.calls:
            callers.setdefault(callee, set()).add(target.name)

    def upstream(name: str, seen: set[str]) -> set[str]:
        for caller in callers.get(name, ()):
            if caller not in seen:
                seen.add(caller)
                upstream(caller, seen)
        return seen

    return {t.name: round((1 + len(upstream(t.name, set()))) / len(targets), 2) for t in targets}


def graph(collector: Collector) -> dict:
    blast = _blast_radius(collector)
    called_by: dict[str, list[str]] = {t.name: [] for t in collector.settings.targets}
    for target in collector.settings.targets:
        for callee in target.calls:
            called_by.setdefault(callee, []).append(target.name)
    return {
        "tenant": collector.settings.tenant,
        "nodes": [{"name": t.name, "tier": t.tier, "blastRadius": blast[t.name], "calls": list(t.calls), "calledBy": called_by[t.name]}
                  for t in collector.settings.targets],
        "edges": [{"from": t.name, "to": callee} for t in collector.settings.targets for callee in t.calls],
    }


def applications(collector: Collector) -> list[dict]:
    apps = []
    with collector.lock:
        for target in collector.settings.targets:
            state = collector.states[target.name]
            if not state.reachable or state.last_seen is None:
                continue                                    # dark: it reports nothing, so it is not in this list
            golden: dict = {}
            rate = None if target.external else collector.rate(target.name)
            if rate:
                # an external dependency is not user traffic: it keeps its readiness and loses its rate
                golden.update(reqPerSec=rate["reqPerSec"], errPct=rate["errPct"], rateAsOfUnix=int(rate["asOf"]))
                if rate["p99Ms"] is not None:
                    golden["p99Ms"] = round(rate["p99Ms"])
            cgroup = state.cgroup
            if cgroup and state.cgroup_at:
                golden["saturationAsOfUnix"] = int(state.cgroup_at)
                for ours, theirs in (("memPsiPct", "memPressureAvg60"), ("cpuPsiPct", "cpuPressureAvg60"), ("ioPsiPct", "ioPressureAvg60")):
                    if isinstance(cgroup.get(theirs), (int, float)):
                        golden[ours] = cgroup[theirs]
                golden["oomKills"] = max(0.0, float(cgroup.get("oomKills") or 0) - (state.oom_baseline or 0))
                current, limit = cgroup.get("memCurrentBytes"), cgroup.get("memMaxBytes")
                if isinstance(current, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
                    # with no memory limit on the container there is no "request" to be close to, and we say nothing
                    golden["memReqPct"] = round(100 * current / limit, 1)
            apps.append({"name": target.name, "tenant": collector.settings.tenant, "ready": state.ready is not False,
                         "observedAt": _iso(state.last_seen), "golden": golden})
    return apps


def incidents(collector: Collector) -> dict:
    blast = _blast_radius(collector)
    with collector.lock:
        items = [{
            "id": i["id"], "service": i["service"], "severity": i["severity"], "status": i["status"], "title": i["title"],
            "firstSeen": _iso(i["firstSeenUnix"]), "resolvedAt": _iso(i["resolvedUnix"]) if i["resolvedUnix"] else None,
            "resolvedBy": i["resolvedBy"], "blastRadius": blast.get(i["service"], 0),
            "rca": "Reported by the compose shim: the service stopped answering its probe. No agent analysed this.",
            "investigationPlan": [f"docker compose ps {i['service']}", f"docker compose logs --tail 100 {i['service']}"],
            "relatedEvents": [],
        } for i in collector.incidents]
    opened = [i for i in items if i["status"] == "open"]
    return {"tenant": collector.settings.tenant, "incidents": items, "incidentMetrics": {
        "criticalOpen": sum(i["severity"] == "critical" for i in opened),
        "warningOpen": sum(i["severity"] == "warning" for i in opened), "infoOpen": 0}}


def status(collector: Collector) -> dict:
    settings = collector.settings
    with collector.lock:
        now = collector.now()
        # the fleet is what we are responsible for and know to exist: no third parties, no undiscovered via-targets
        fleet = [t for t in settings.targets if not t.external and collector.states[t.name].known]
        dark = [(t, collector.states[t.name]) for t in fleet if not collector.states[t.name].reachable]
        total = len(fleet)
        history = [{"t": _iso(index * BUCKET_S), "requests": round(values[0], 1), "requestErrors": round(values[1], 1)}
                   for index, values in sorted(collector.history.items())]
        resolved = [i for i in collector.incidents if i["status"] == "resolved"]
        tenant: dict = {
            "services": total,
            "servicesDark": len(dark),
            "serviceCoveragePct": round(100 * (total - len(dark)) / total, 1) if total else 0,
            "darkServices": [{"name": t.name, "lastEventAt": _iso(s.last_seen or s.first_checked or collector.started_at)}
                             for t, s in dark],
            "signalsHistory": history,
            "incidents": {"openNow": sum(i["status"] == "open" for i in collector.incidents)},
            "sampledIncidents": len(collector.incidents),
        }
        if collector.incidents:
            tenant["autoResolvedPct"] = round(100 * len(resolved) / len(collector.incidents))
        return {
            "generatedAt": _iso(now),
            "tenantStats": {"tenants": {settings.tenant: tenant}},
            # The collector plays the cluster agent. While its loop runs it is "connected";
            # lastMessageUnix is the last finished cycle, so a stuck loop shows up as silence.
            "clusterAgentStats": {settings.tenant: {"cluster": settings.cluster, "connected": collector.last_cycle_at is not None,
                                                    "lastMessageUnix": int(collector.last_cycle_at or collector.started_at)}},
            "unmappedServices": 0,
        }


def analytics(collector: Collector) -> dict:
    # No agent, so no baselines, patterns or precursors. Left empty on purpose: inventing them would be lying.
    return {"tenant": collector.settings.tenant, "baselines": [], "patterns": [], "precursorMatches": []}


def debug(collector: Collector) -> list[dict]:
    """What the collector saw last cycle. The first place to look when a target stays dark."""
    with collector.lock:
        return [{"name": t.name, "probe": t.probe or t.tcp or t.via, "vitals": t.vitals, "known": s.known,
                 "reachable": s.reachable, "ready": s.ready,
                 "detail": s.detail, "probeMs": round(s.probe_ms) if s.probe_ms else None, "hasVitals": s.has_vitals,
                 "rate": None if t.external else collector.rate(t.name)}
                for t in collector.settings.targets for s in [collector.states[t.name]]]
