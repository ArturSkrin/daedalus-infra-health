"""Normalise five raw Triage responses into one typed Bundle.

The catalog warns that the core omits most fields when it has nothing to
report, and that a missing value means "not measured". This module is the only
place that touches raw JSON. It never raises on a missing or malformed field:
what is absent becomes None, and the engine decides what None means. Anything
surprising is recorded in `Bundle.problems` so it can be shown, not swallowed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ----------------------------------------------------------------- coercion ---

def num(value) -> float | None:
    """A real number, or None. Booleans and strings are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value) -> list:
    return value if isinstance(value, list) else []


def text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def as_dt(value, tz) -> datetime | None:
    """ISO string or unix seconds -> aware datetime in `tz`; None if unreadable."""
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
        seconds = num(value)
        if seconds is not None:
            return datetime.fromtimestamp(seconds, tz)
    except (ValueError, OverflowError, OSError):
        return None
    return None


# -------------------------------------------------------------------- shapes ---

@dataclass(frozen=True)
class Rate:
    rps: float
    err_pct: float
    p99_ms: float | None
    age_s: float | None          # None: the block carries no rateAsOfUnix, so it cannot be called fresh


@dataclass(frozen=True)
class Saturation:
    mem_stall_pct: float | None
    cpu_stall_pct: float | None
    io_stall_pct: float | None
    oom_kills: float | None
    mem_of_request_pct: float | None
    age_s: float | None

    @property
    def worst_stall_pct(self) -> float:
        return max((v for v in (self.mem_stall_pct, self.cpu_stall_pct, self.io_stall_pct) if v is not None), default=0.0)


@dataclass(frozen=True)
class Service:
    name: str
    tier: int | None = None
    blast_radius: float | None = None
    called_by: tuple[str, ...] = ()
    reporting: bool = False      # present in /applications
    ready: bool | None = None
    rate: Rate | None = None
    saturation: Saturation | None = None


@dataclass(frozen=True)
class Incident:
    id: str
    service: str
    severity: str
    status: str
    title: str
    first_seen: datetime | None
    resolved_by: str | None
    rca: str | None
    plan: tuple[str, ...]
    related: tuple[str, ...]
    blast_radius: float

    @property
    def is_open(self) -> bool:
        return self.status == "open"


@dataclass(frozen=True)
class Bucket:
    t: datetime | None
    requests: float
    errors: float

    @property
    def err_pct(self) -> float:
        return 100 * self.errors / self.requests if self.requests else 0.0


@dataclass(frozen=True)
class Precursor:
    service: str
    pattern: str | None
    confidence: float
    matched: int
    total: int
    matched_steps: tuple[str, ...]
    remaining_steps: tuple[str, ...]

    @property
    def progress(self) -> float:
        return self.matched / self.total if self.total > 0 else 0.0


@dataclass(frozen=True)
class DarkService:
    name: str
    silent_s: float | None


@dataclass
class Bundle:
    tenant: str
    now: datetime
    tenant_present: bool = False
    agent_connected: bool | None = None     # None: the core did not say
    agent_silent_s: float | None = None
    cluster: str | None = None
    services_total: int | None = None
    coverage_pct: float | None = None
    dark_count: int | None = None
    dark: list[DarkService] = field(default_factory=list)
    unmapped: int = 0
    services: dict[str, Service] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)
    critical_open: int = 0
    warning_open: int = 0
    open_now: int = 0
    history: list[Bucket] = field(default_factory=list)
    weekly_incident_counts: list[float] = field(default_factory=list)
    prediction_hits: int = 0
    prediction_misses: int = 0
    prediction_precision_pct: float | None = None
    prediction_lead_ms: float | None = None
    sampled_incidents: int = 0
    auto_resolved_pct: float | None = None
    repeat_rate_pct: float | None = None
    events: dict[str, float] = field(default_factory=dict)
    signals_by_type: dict[str, float] = field(default_factory=dict)
    top_signal_sources: list[dict] = field(default_factory=list)
    precursors: list[Precursor] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def service(self, name: str) -> Service:
        return self.services.get(name) or Service(name=name)


# ------------------------------------------------------------- normalisation ---

def _agent(status: dict, tenant: str, now: datetime, bundle: Bundle) -> None:
    """clusterAgentStats may be keyed by tenant or by cluster, or be a list."""
    stats = status.get("clusterAgentStats")
    if isinstance(stats, dict) and isinstance(stats.get(tenant), dict):
        candidates = [stats[tenant]]
    else:
        values = list(stats.values()) if isinstance(stats, dict) else as_list(stats)
        candidates = [v for v in values if isinstance(v, dict) and v.get("tenant") == tenant]
    flags = [c.get("connected") for c in candidates if isinstance(c.get("connected"), bool)]
    if not flags:
        bundle.problems.append("the core did not report the cluster agent link for this tenant")
        return
    bundle.agent_connected = any(flags)
    bundle.cluster = next((text(c.get("cluster")) for c in candidates if text(c.get("cluster"))), None)
    last = [as_dt(c.get("lastMessageUnix"), now.tzinfo) for c in candidates]
    last = [t for t in last if t]
    if last:
        bundle.agent_silent_s = max(0.0, (now - max(last)).total_seconds())


def _services(raw: dict, now: datetime, bundle: Bundle) -> None:
    merged: dict[str, dict] = {}
    for node in as_list(as_dict(raw.get("graph")).get("nodes")):
        name = text(as_dict(node).get("name"))
        if name:
            tier = num(node.get("tier"))
            merged[name] = {
                "tier": int(tier) if tier is not None else None,
                "blast_radius": num(node.get("blastRadius")),
                "called_by": tuple(n for n in as_list(node.get("calledBy")) if isinstance(n, str)),
            }

    applications = raw.get("applications")
    if isinstance(applications, dict):          # some cores wrap the list
        applications = applications.get("applications")
    for app in as_list(applications):
        name = text(as_dict(app).get("name"))
        if not name:
            continue
        golden = as_dict(app.get("golden"))
        entry = merged.setdefault(name, {})
        entry["reporting"] = True
        entry["ready"] = app.get("ready") if isinstance(app.get("ready"), bool) else None

        rps, err = num(golden.get("reqPerSec")), num(golden.get("errPct"))
        if rps is not None and err is not None:
            as_of = num(golden.get("rateAsOfUnix"))
            entry["rate"] = Rate(rps, err, num(golden.get("p99Ms")), None if as_of is None else max(0.0, now.timestamp() - as_of))
        elif rps is not None:
            bundle.problems.append(f"{name}: request rate without an error share, excluded")

        stalls = [num(golden.get(k)) for k in ("memPsiPct", "cpuPsiPct", "ioPsiPct")]
        if any(v is not None for v in stalls) or num(golden.get("oomKills")) is not None:
            as_of = num(golden.get("saturationAsOfUnix"))
            entry["saturation"] = Saturation(*stalls, num(golden.get("oomKills")), num(golden.get("memReqPct")),
                                             None if as_of is None else max(0.0, now.timestamp() - as_of))

    bundle.services = {name: Service(name=name, **fields) for name, fields in merged.items()}


def _incidents(raw: dict, now: datetime, bundle: Bundle) -> None:
    block = as_dict(raw.get("incidents"))
    for item in as_list(block.get("incidents")):
        item = as_dict(item)
        bundle.incidents.append(Incident(
            id=text(item.get("id")) or f"incident-{len(bundle.incidents) + 1}",
            service=text(item.get("service")) or "unknown service",
            severity=text(item.get("severity")) or "warning",
            status=text(item.get("status")) or "open",
            title=text(item.get("title")) or text(item.get("message")) or "incident",
            first_seen=as_dt(item.get("firstSeen"), now.tzinfo),
            resolved_by=text(item.get("resolvedBy")),
            rca=text(item.get("rca")),
            plan=tuple(s for s in as_list(item.get("investigationPlan")) if isinstance(s, str)),
            related=tuple(s for s in as_list(item.get("relatedEvents")) if isinstance(s, str)),
            blast_radius=num(item.get("blastRadius")) or 0.0,
        ))

    metrics = as_dict(block.get("incidentMetrics"))
    opened = [i for i in bundle.incidents if i.is_open]
    # The summary counts win; when the core omits them, count the list ourselves.
    critical, warning = num(metrics.get("criticalOpen")), num(metrics.get("warningOpen"))
    bundle.critical_open = int(critical) if critical is not None else sum(i.severity == "critical" for i in opened)
    bundle.warning_open = int(warning) if warning is not None else sum(i.severity == "warning" for i in opened)


def _tenant(block: dict, now: datetime, bundle: Bundle) -> None:
    total, dark, coverage = num(block.get("services")), num(block.get("servicesDark")), num(block.get("serviceCoveragePct"))
    bundle.services_total = int(total) if total is not None else None
    bundle.dark_count = int(dark) if dark is not None else None
    if coverage is None and total and dark is not None:
        coverage = 100 * (total - dark) / total
    bundle.coverage_pct = coverage

    for item in as_list(block.get("darkServices")):
        name = text(as_dict(item).get("name"))
        if name:
            last = as_dt(item.get("lastEventAt"), now.tzinfo)
            bundle.dark.append(DarkService(name, (now - last).total_seconds() if last else None))

    for raw_bucket in as_list(block.get("signalsHistory")):
        raw_bucket = as_dict(raw_bucket)
        requests, errors = num(raw_bucket.get("requests")), num(raw_bucket.get("requestErrors"))
        if requests is not None and errors is not None:
            bundle.history.append(Bucket(as_dt(raw_bucket.get("t"), now.tzinfo), requests, errors))

    open_now = num(as_dict(block.get("incidents")).get("openNow"))
    bundle.open_now = int(open_now) if open_now is not None else bundle.critical_open + bundle.warning_open

    bundle.prediction_hits = int(num(block.get("predictionHits")) or 0)
    bundle.prediction_misses = int(num(block.get("predictionMisses")) or 0)
    bundle.prediction_precision_pct = num(block.get("predictionPrecisionPct"))
    bundle.prediction_lead_ms = num(block.get("predictionAvgLeadMs")) if bundle.prediction_hits else None
    bundle.sampled_incidents = int(num(block.get("sampledIncidents")) or 0)
    if bundle.sampled_incidents:
        bundle.auto_resolved_pct = num(block.get("autoResolvedPct"))
        bundle.repeat_rate_pct = num(block.get("repeatRatePct"))

    bundle.events = {k: v for k, v in ((k, num(v)) for k, v in as_dict(block.get("events")).items()) if v is not None}
    bundle.signals_by_type = {k: v for k, v in ((k, num(v)) for k, v in as_dict(block.get("signalsByType")).items()) if v is not None}
    bundle.top_signal_sources = [s for s in as_list(block.get("topSignalSources")) if isinstance(s, dict)]


def _analytics(raw: dict, bundle: Bundle) -> None:
    analytics = as_dict(raw.get("analytics"))
    weeks: dict[str, float] = {}
    for baseline in as_list(analytics.get("baselines")):
        for week, count in as_dict(as_dict(baseline).get("weeklyIncidentCounts")).items():
            if num(count) is not None:
                weeks[week] = weeks.get(week, 0.0) + num(count)
    bundle.weekly_incident_counts = list(weeks.values())

    for match in as_list(analytics.get("precursorMatches")):
        match = as_dict(match)
        service, confidence = text(match.get("service")), num(match.get("confidence"))
        if service and confidence is not None:
            bundle.precursors.append(Precursor(
                service=service,
                pattern=text(match.get("patternId")),
                confidence=confidence,
                matched=int(num(match.get("matchedSteps")) or 0),
                total=int(num(match.get("totalSteps")) or 0),
                matched_steps=tuple(s for s in as_list(match.get("matched")) if isinstance(s, str)),
                remaining_steps=tuple(s for s in as_list(match.get("remaining")) if isinstance(s, str)),
            ))


def normalize(raw: dict) -> Bundle:
    raw = as_dict(raw)
    now = as_dt(raw.get("now"), timezone.utc) or datetime.now(timezone.utc)
    tenant = text(raw.get("tenant")) or ""
    bundle = Bundle(tenant=tenant, now=now)

    status = as_dict(raw.get("status"))
    block = as_dict(as_dict(status.get("tenantStats")).get("tenants")).get(tenant)
    bundle.tenant_present = isinstance(block, dict)
    unmapped = num(status.get("unmappedServices"))
    bundle.unmapped = int(unmapped) if unmapped is not None else 0

    _agent(status, tenant, now, bundle)
    _services(raw, now, bundle)
    _incidents(raw, now, bundle)
    _tenant(as_dict(block), now, bundle)
    _analytics(raw, bundle)
    return bundle
