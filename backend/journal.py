"""What changed, and why: an append-only journal of decisions per tenant.

The engine is stateless, it judges one snapshot at a time. This module remembers
the previous snapshot and writes an event every time the word, an indicator, or
the incident queue changes, together with the reason line the screen showed at
that moment. It is the answer to "why did this turn red at 14:07".

Only transitions are recorded. Captions and ages change on every poll ("data is
13 s old"), so an event is written when a *state* changes, not when its wording
does. Events survive a restart: the journal lives as JSON on a volume.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

MAX_EVENTS = 500

INDICATOR_TITLES = {"users": "Users now", "forecast": "What's brewing", "trust": "Can we trust it", "day": "How the day went"}
SEVERITY_LEVEL = {"critical": "bad", "warning": "warn", "info": "muted"}

_lock = threading.Lock()
_snapshots: dict[str, dict] = {}
_events: dict[str, list[dict]] = {}
_loaded: set[str] = set()


def _dir() -> Path | None:
    path = Path(os.environ.get("TRACKER_DATA_DIR", "/data"))
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path if os.access(path, os.W_OK) else None
    except OSError:
        return None


def _file(tenant: str) -> Path | None:
    base = _dir()
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in tenant) or "tenant"
    return base / f"journal-{safe}.json" if base else None


def _load(tenant: str) -> None:
    if tenant in _loaded:
        return
    _loaded.add(tenant)
    path = _file(tenant)
    if not path or not path.exists():
        return
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        _snapshots[tenant] = saved.get("snapshot") or {}
        _events[tenant] = list(saved.get("events") or [])[-MAX_EVENTS:]
    except (OSError, ValueError):
        pass


def _save(tenant: str) -> None:
    path = _file(tenant)
    if not path:
        return
    try:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"snapshot": _snapshots.get(tenant, {}), "events": _events.get(tenant, [])}), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass        # a read-only disk must not stop the tracker from answering


def snapshot_of(view: dict) -> dict:
    """The part of a view whose change is worth an event."""
    return {
        "verdict": view["decision"]["verdict"],
        "word": view["decision"]["word"],
        "level": view["decision"]["level"],
        "reason": view["decision"]["reason"],
        "indicators": {i["id"]: {"state": i["state"], "label": i["label"], "level": i["level"], "caption": i["caption"]}
                       for i in view["indicators"]},
        "queue": {q["id"]: {"service": q["service"], "severity": q["severity"], "title": q["title"]} for q in view["queue"]},
        "accepted": {a["service"]: {"kind": a["kind"], "reason": a["reason"], "until": a["until"]} for a in view.get("accepted", [])},
    }


def _event(at: str, kind: str, indicator: str | None, level: str, title: str, detail: str, **extra) -> dict:
    return {"at": at, "kind": kind, "indicator": indicator, "level": level, "title": title, "detail": detail, **extra}


def diff(previous: dict | None, current: dict, at: str) -> list[dict]:
    """Events that turn `previous` into `current`. The first observation yields one 'journal started' event."""
    if previous is None:
        return [_event(at, "started", "verdict", current["level"], f"Journal started: {current['word']}", current["reason"])]
    events: list[dict] = []
    if previous["verdict"] != current["verdict"]:
        events.append(_event(at, "verdict", "verdict", current["level"], f"{previous['word']} → {current['word']}", current["reason"],
                             **{"from": previous["verdict"], "to": current["verdict"]}))
    for key, now in current["indicators"].items():
        before = previous["indicators"].get(key)
        if before and before["state"] != now["state"]:
            title = f"{INDICATOR_TITLES.get(key, key)}: {before['label']} → {now['label']}"
            change = {"from": before["state"], "to": now["state"]}
            events.append(_event(at, "indicator", key, now["level"], title, now["caption"], **change))
    for incident_id, item in current["queue"].items():
        if incident_id not in previous["queue"]:
            events.append(_event(at, "incident", "users", SEVERITY_LEVEL.get(item["severity"], "warn"),
                                 f"Incident opened: {item['service']}", item["title"], incident=incident_id))
    accepted_before = previous.get("accepted", {})      # snapshots older than acks have none
    for incident_id, item in previous["queue"].items():
        if incident_id not in current["queue"] and item["service"] not in current["accepted"]:
            title = f"Incident closed: {item['service']}"
            events.append(_event(at, "incident", "users", "good", title, item["title"], incident=incident_id))
    for service, ack in current["accepted"].items():
        if service not in accepted_before:
            until = f" until {ack['until'][:10]}" if ack["until"] else ""
            events.append(_event(at, "ack", None, "muted", f"Accepted as {ack['kind']}: {service}", f"{ack['reason']}{until}"))
    for service in accepted_before:
        if service not in current["accepted"]:
            events.append(_event(at, "ack", None, "warn", f"No longer accepted: {service}",
                                 "the window ended, it got worse, it was fine for a day, or a person lifted it"))
    return events


def observe(tenant: str, view: dict, at: str | None = None) -> list[dict]:
    """Record whatever changed since the last observation of this tenant. Returns the new events."""
    at = at or datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    with _lock:
        _load(tenant)
        current = snapshot_of(view)
        new_events = diff(_snapshots.get(tenant), current, at)
        _snapshots[tenant] = current
        if new_events:
            _events[tenant] = (_events.get(tenant, []) + new_events)[-MAX_EVENTS:]
            _save(tenant)
        elif tenant not in _events:
            _events[tenant] = []
        return new_events


def events(tenant: str, limit: int = 200) -> list[dict]:
    """Newest first."""
    with _lock:
        _load(tenant)
        return list(reversed(_events.get(tenant, [])))[:limit]


def reset() -> None:
    """Tests only."""
    with _lock:
        _snapshots.clear()
        _events.clear()
        _loaded.clear()
