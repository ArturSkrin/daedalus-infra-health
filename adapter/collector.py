"""One collection cycle, and the state it accumulates.

Counters from the in-app vitals endpoint are cumulative (like Prometheus), so
rates are deltas between cycles and a restart of the app shows up as a counter
reset, not as a negative rate. Rates are reported over a sliding five-minute
window: a hobby-scale app gets a handful of requests a minute, and a verdict
that flips on a single failed request would teach people to ignore it.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from adapter import sources
from adapter.config import Settings, Target

BUCKET_S = 300
BUCKETS_KEPT = 288              # 24 h, the same depth the Triage core keeps
RATE_WINDOW_S = 300             # real traffic reported by the app
PROBE_WINDOW_S = 60             # our own probes: a service that answers again must not look broken for five more minutes
MIN_ERRORS_TO_REPORT = 3        # below this, in under MIN_REQUESTS requests, an error share is noise
MIN_REQUESTS_TO_REPORT = 50
CYCLES_TO_OPEN = 2              # consecutive failed cycles before an incident opens
CYCLES_TO_CLOSE = 2
EXTERNAL_EVERY_S = 60
INCIDENTS_KEPT_S = 24 * 3600


@dataclass
class Window:
    t: float
    probe_requests: float
    probe_errors: float
    requests: float             # real traffic, from the app's own counters
    errors: float
    buckets: dict[str, float]


@dataclass
class TargetState:
    first_checked: float | None = None
    last_seen: float | None = None          # last time the name resolved and something answered or refused
    reachable: bool = False
    known: bool = True                      # a via-target exists for us only once its parent has spoken of it
    ready: bool | None = None
    detail: str = "not checked yet"
    probe_ms: float | None = None
    has_vitals: bool = False
    previous: dict | None = None            # last cumulative vitals sample
    windows: deque = field(default_factory=deque)
    cgroup: dict | None = None
    cgroup_at: float | None = None
    oom_baseline: float | None = None
    failing_cycles: int = 0
    healthy_cycles: int = 0
    last_external_check: float = 0.0


def _delta(current, previous) -> float:
    """Cumulative counter delta that survives a reset of the counter."""
    current = float(current or 0)
    if previous is None or current < float(previous):
        return current
    return current - float(previous)


class Collector:
    def __init__(self, settings: Settings, now=time.time):
        self.settings = settings
        self.now = now
        self.lock = threading.Lock()
        self.states: dict[str, TargetState] = {t.name: TargetState(known=not t.via) for t in settings.targets}
        self.history: dict[int, list[float]] = {}        # bucket index -> [requests, errors]
        self.incidents: list[dict] = []
        self.started_at = now()
        self.last_cycle_at: float | None = None
        self.sequence = 0
        self._path = Path(settings.data_dir) / "collector-state.json"
        self._load()

    # ------------------------------------------------------------ persistence ---
    # History and incidents survive a restart of the collector. The Triage core keeps them in memory
    # and starts every restart blind to the last day; a file on a volume is all it takes not to.

    def _load(self) -> None:
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        oldest = int(self.now() // BUCKET_S) - BUCKETS_KEPT
        self.history = {int(k): v for k, v in saved.get("history", {}).items() if int(k) > oldest}
        self.incidents = saved.get("incidents", [])
        self.sequence = saved.get("sequence", 0)
        for name, seen in saved.get("seen", {}).items():
            if name in self.states:
                # without this a restart of the collector would turn a stopped container back into a merely dark one
                self.states[name].last_seen = seen
                self.states[name].known = True

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(".tmp")
            seen = {name: s.last_seen for name, s in self.states.items() if s.last_seen is not None}
            temporary.write_text(json.dumps({"history": self.history, "incidents": self.incidents, "sequence": self.sequence,
                                             "seen": seen}), encoding="utf-8")
            temporary.replace(self._path)
        except OSError:
            pass        # a read-only disk must not stop the collector from answering

    # ------------------------------------------------------------------ cycle ---

    def cycle(self) -> None:
        now = self.now()
        samples = {t.name: self._observe(t, now) for t in self.settings.targets if not t.via}
        with self.lock:
            fleet_requests = fleet_errors = 0.0
            # direct targets first: a via-target reads what its parent reported in this same cycle
            for target in sorted(self.settings.targets, key=lambda t: bool(t.via)):
                if target.via:
                    self._apply_via(target, now)
                    continue
                requests, errors = self._apply(target, samples[target.name], now)
                if not target.external:
                    fleet_requests += requests
                    fleet_errors += errors
            bucket = self.history.setdefault(int(now // BUCKET_S), [0.0, 0.0])
            bucket[0] += fleet_requests
            bucket[1] += fleet_errors
            for index in [i for i in self.history if i <= int(now // BUCKET_S) - BUCKETS_KEPT]:
                del self.history[index]
            self.incidents = [i for i in self.incidents if i["status"] == "open" or now - i["resolvedUnix"] < INCIDENTS_KEPT_S]
            self.last_cycle_at = now
            self._save()

    def _observe(self, target: Target, now: float):
        """Network calls only, outside the lock. Returns (probe or None, vitals or None, skipped)."""
        state = self.states[target.name]
        if target.external and now - state.last_external_check < EXTERNAL_EVERY_S:
            return None, None, True
        timeout = self.settings.timeout_s
        probe = None
        if target.probe:
            probe = sources.http_probe(target.probe, timeout, target.headers)
        elif target.tcp:
            probe = sources.tcp_probe(target.tcp, timeout)
        vitals = sources.fetch_vitals(target.vitals, timeout, self.settings.vitals_token) if target.vitals else None
        return probe, vitals, False

    def _apply(self, target: Target, sample, now: float) -> tuple[float, float]:
        probe, vitals, skipped = sample
        state = self.states[target.name]
        if skipped:
            return 0.0, 0.0
        state.first_checked = state.first_checked or now
        state.last_external_check = now
        state.has_vitals = vitals is not None

        state.reachable = bool((probe and probe.reachable) or vitals is not None)
        if probe:
            state.detail, state.probe_ms = probe.detail, probe.ms
        if not state.reachable and state.last_seen is None:
            # Never seen: we cannot tell a service that is down from one that is not on our network.
            # That is "dark", not "down": it never counts as an error, only against trust.
            state.ready = None
            return 0.0, 0.0
        if not state.reachable:
            # It was here and now its name does not resolve. Under compose a running container never leaves
            # its network, so the name goes away only when the container stops. That is down, and we saw it happen.
            state.reachable = True
            probe = sources.Probe(True, False, None, "gone from the network: the container stopped or was removed")
            state.detail, state.probe_ms = probe.detail, None
        else:
            state.last_seen = now

        ready = probe.ok if probe else True
        if vitals is not None and vitals.get("ready") is False:
            ready = False
            failed = [name for name, dep in (vitals.get("deps") or {}).items() if isinstance(dep, dict) and not dep.get("ok")]
            state.detail = f"reports a failed dependency: {', '.join(failed)}" if failed else "reports itself not ready"
        state.ready = ready

        # every probe is one request we made ourselves; real traffic is kept apart because it ages differently
        probe_requests, probe_errors = (1.0, 0.0 if probe.ok else 1.0) if probe else (0.0, 0.0)
        requests, errors, buckets = 0.0, 0.0, {}
        if vitals is not None:
            previous = state.previous
            if previous is not None:
                # the first sample only sets the baseline: totals since the app started are not traffic of this cycle
                requests += _delta(vitals.get("requests"), previous.get("requests"))
                errors += _delta(vitals.get("errors"), previous.get("errors"))
                current_buckets = vitals.get("durationBucketsMs") or {}
                buckets = {le: _delta(count, (previous.get("durationBucketsMs") or {}).get(le)) for le, count in current_buckets.items()}
            state.previous = vitals
            cgroup = vitals.get("cgroup")
            if isinstance(cgroup, dict):
                if state.oom_baseline is None or float(cgroup.get("oomKills") or 0) < state.oom_baseline:
                    state.oom_baseline = float(cgroup.get("oomKills") or 0)
                state.cgroup, state.cgroup_at = cgroup, now

        state.windows.append(Window(now, probe_requests, probe_errors, requests, errors, buckets))
        while state.windows and now - state.windows[0].t > RATE_WINDOW_S:
            state.windows.popleft()

        if not target.external:
            self._track_incident(target, state, now)
        return requests + probe_requests, errors + probe_errors

    def _apply_via(self, target: Target, now: float) -> None:
        parent_name, _, dependency = target.via.partition(".")
        parent, state = self.states.get(parent_name), self.states[target.name]
        report = ((parent.previous or {}).get("deps") or {}).get(dependency) if parent and parent.has_vitals else None
        state.first_checked = state.first_checked or now
        if not isinstance(report, dict):
            # Parent silent about it. If it never spoke of it we do not count the service at all;
            # if it used to, the service has gone dark.
            # While the parent itself is down or out of sight we simply do not know, and an unknown
            # service must not drag coverage down and turn a plain outage into BLIND.
            state.known = bool(state.last_seen and parent and parent.reachable and parent.ready)
            state.reachable, state.ready, state.detail = False, None, f"{parent_name} does not report it"
            return
        state.known, state.reachable, state.last_seen = True, True, now
        state.ready = bool(report.get("ok"))
        state.probe_ms = report.get("ms") if isinstance(report.get("ms"), (int, float)) else None
        state.detail = f"answers {parent_name}" if state.ready else str(report.get("error") or f"does not answer {parent_name}")
        self._track_incident(target, state, now)

    def _track_incident(self, target: Target, state: TargetState, now: float) -> None:
        open_incident = next((i for i in self.incidents if i["service"] == target.name and i["status"] == "open"), None)
        if state.ready is False:
            state.failing_cycles, state.healthy_cycles = state.failing_cycles + 1, 0
            if not open_incident and state.failing_cycles >= CYCLES_TO_OPEN:
                self.sequence += 1
                self.incidents.append({
                    "id": f"shim-{self.sequence}", "service": target.name, "status": "open",
                    "severity": "critical" if target.tier == 1 else "warning",
                    "firstSeenUnix": now - (CYCLES_TO_OPEN - 1) * self.settings.interval_s, "resolvedUnix": None, "resolvedBy": None,
                    "title": f"{target.name} is not answering ({state.detail})",
                })
        else:
            state.healthy_cycles, state.failing_cycles = state.healthy_cycles + 1, 0
            if open_incident and state.healthy_cycles >= CYCLES_TO_CLOSE:
                # nobody touched it: in Triage terms this is an auto-resolved incident
                open_incident.update(status="resolved", resolvedUnix=now, resolvedBy="agent")

    # ------------------------------------------------------------------ reads ---

    def rate(self, name: str) -> dict | None:
        """Traffic over the sliding window, or None when there is nothing to base it on."""
        state = self.states[name]
        if not state.windows:
            return None
        span = max(self.settings.interval_s, state.windows[-1].t - state.windows[0].t + self.settings.interval_s)
        latest = state.windows[-1].t
        recent = [w for w in state.windows if latest - w.t < PROBE_WINDOW_S]
        requests = sum(w.requests for w in state.windows) + sum(w.probe_requests for w in recent)
        errors = sum(w.errors for w in state.windows) + sum(w.probe_errors for w in recent)
        # low-traffic guard: one failed request out of five is not "20 % of users"
        significant = errors >= MIN_ERRORS_TO_REPORT or requests >= MIN_REQUESTS_TO_REPORT
        totals: dict[str, float] = {}
        for window in state.windows:
            for le, count in window.buckets.items():
                totals[le] = totals.get(le, 0.0) + count
        return {"reqPerSec": round(requests / span, 3), "errPct": round(100 * errors / requests, 2) if requests and significant else 0.0,
                "p99Ms": _p99(totals) if totals else state.probe_ms, "asOf": state.windows[-1].t,
                "requests": requests, "errors": errors}


def _p99(buckets: dict[str, float]) -> float | None:
    """Upper bound of the histogram bucket that holds the 99th percentile. Buckets are cumulative, keyed by 'le'."""
    ordered = sorted(((float("inf") if le == "+Inf" else float(le)), count) for le, count in buckets.items())
    total = ordered[-1][1] if ordered else 0
    if total <= 0:
        return None
    for le, count in ordered:
        if count >= 0.99 * total:
            return None if le == float("inf") else le
    return None
