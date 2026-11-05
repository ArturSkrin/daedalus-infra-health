"""Acknowledgements: a human says "known, leave it" about one service, for a while.

An accepted service keeps its incident on screen, marked, but the verdict stops leaning on it, so a problem
everybody already knows about cannot hide a new one. An ack ends by itself:
  - when its window runs out;
  - when the service gets worse than it was when it was accepted (a warning becomes critical);
  - when the service has been fine for a day: that problem is gone, and the next one is news.
Stored as JSON next to the journal. Service names are fleet names, "<host>:<service>".
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

KINDS = ("expected", "noise")       # known and accepted / not a problem at all, the rule fired for nothing
MAX_DAYS = 30
FIXED_AFTER_S = 24 * 3600
BAD_STAMP_EVERY_S = 300             # how often a still-broken service rewrites the file
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

_lock = threading.Lock()
_acks: dict[str, dict] | None = None


def _file() -> Path:
    return Path(os.environ.get("TRACKER_DATA_DIR", "/data")) / "acks.json"


def _loaded() -> dict[str, dict]:
    global _acks
    if _acks is None:
        try:
            _acks = json.loads(_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _acks = {}
    return _acks


def _save() -> None:
    try:
        path = _file()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(_loaded()), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass        # a read-only disk must not stop the tracker from answering


def listing() -> list[dict]:
    with _lock:
        return [{"service": name, **ack} for name, ack in sorted(_loaded().items())]


def add(service: str, kind: str, days: int, reason: str, severity: str, now: float | None = None) -> dict:
    service, reason = service.strip(), reason.strip()
    if not service or len(service) > 200:
        raise ValueError("service must be a fleet name, <host>:<service>")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be from 1 to {MAX_DAYS}")
    if not reason or len(reason) > 200:
        raise ValueError("say why, in under 200 characters")
    now = time.time() if now is None else now
    ack = {"kind": kind, "reason": reason, "severity": severity if severity in SEVERITY_RANK else "warning",
           "since": now, "until": now + days * 86400, "lastBadUnix": now}
    with _lock:
        _loaded()[service] = ack
        _save()
    return {"service": service, **ack}


def remove(service: str) -> bool:
    with _lock:
        found = _loaded().pop(service, None) is not None
        if found:
            _save()
        return found


def _end_or_stamp(acks: dict[str, dict], incidents: list[dict], apps: list[dict], name, now: float) -> bool:
    """End the acks that no longer hold, and note when each accepted service was last seen broken."""
    changed = False
    for service in [s for s, ack in acks.items() if now >= ack["until"]]:
        del acks[service]
        changed = True
    opened = [i for i in incidents if i.get("status") == "open" and name(i.get("service")) in acks]
    for incident in opened:
        ack = acks.get(name(incident.get("service")))
        if ack and SEVERITY_RANK.get(incident.get("severity"), 1) > SEVERITY_RANK.get(ack["severity"], 1):
            del acks[name(incident.get("service"))]
            changed = True
    broken = {name(i.get("service")) for i in opened} | {name(a.get("name")) for a in apps if a.get("ready") is False}
    present = broken | {name(a.get("name")) for a in apps}
    for service, ack in list(acks.items()):
        if service in broken:
            if now - ack["lastBadUnix"] >= BAD_STAMP_EVERY_S:
                ack["lastBadUnix"] = now
                changed = True
        elif service in present and now - ack["lastBadUnix"] >= FIXED_AFTER_S:
            del acks[service]           # an absent service proves nothing: its agent may simply be silent
            changed = True
    return changed


def apply(data: dict, prefix: str = "", now: float | None = None) -> dict:
    """The raw bundle with accepted incidents and services marked; acks that no longer hold are ended first.

    prefix turns the bundle's service names into fleet names: "" for the fleet, "<host>:" for one host's view.
    An accepted incident gets status "accepted", so nothing downstream counts it as open.
    """
    now = time.time() if now is None else now
    block = data.get("incidents") if isinstance(data.get("incidents"), dict) else {}
    incidents = [i for i in block.get("incidents") or [] if isinstance(i, dict)]
    apps = [a for a in data.get("applications") or [] if isinstance(a, dict)]

    def name(service) -> str:
        return f"{prefix}{service}"

    with _lock:
        acks = _loaded()
        if _end_or_stamp(acks, incidents, apps, name, now):
            _save()
        current = {service: dict(ack) for service, ack in acks.items()}
    if not current:
        return data

    def mark(ack: dict) -> dict:
        return {"kind": ack["kind"], "reason": ack["reason"], "until": ack["until"]}

    marked, accepted = [], {"critical": 0, "warning": 0}
    for incident in incidents:
        ack = current.get(name(incident.get("service")))
        if ack and incident.get("status") == "open":
            accepted[incident.get("severity")] = accepted.get(incident.get("severity"), 0) + 1
            incident = {**incident, "status": "accepted", "accepted": mark(ack)}
        marked.append(incident)
    metrics = dict(block.get("incidentMetrics") or {})
    for severity, key in (("critical", "criticalOpen"), ("warning", "warningOpen")):
        if isinstance(metrics.get(key), (int, float)):
            metrics[key] = max(0, metrics[key] - accepted[severity])
    out = {**data, "incidents": {**block, "incidents": marked, "incidentMetrics": metrics},
           "applications": [{**a, "accepted": mark(current[name(a.get("name"))])} if name(a.get("name")) in current else a
                            for a in apps]}

    status = data.get("status") if isinstance(data.get("status"), dict) else {}
    tenants = (status.get("tenantStats") or {}).get("tenants") or {}
    tenant = tenants.get(data.get("tenant")) if isinstance(tenants, dict) else None
    count = sum(accepted.values())
    if isinstance(tenant, dict) and count and isinstance((tenant.get("incidents") or {}).get("openNow"), (int, float)):
        tenant = {**tenant, "incidents": {**tenant["incidents"], "openNow": max(0, tenant["incidents"]["openNow"] - count)}}
        out["status"] = {**status, "tenantStats": {**status["tenantStats"], "tenants": {**tenants, data["tenant"]: tenant}}}
    return out


def reset() -> None:
    """Tests only."""
    global _acks
    with _lock:
        _acks = None
