"""Response models of the API.

presentation.py builds plain dicts so that it, the engine and the static export
run on the standard library alone. These models are the contract on top: FastAPI
validates every response against them, publishes them as OpenAPI, and the
frontend types in frontend/src/api.gen.ts are generated from that document
(`npm run gen:types`), so the two sides cannot drift silently.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["good", "warn", "bad", "muted"]
Verdict = Literal["all_clear", "schedule", "act_now", "blind"]
IndicatorId = Literal["users", "forecast", "trust", "day"]


class Fact(BaseModel):
    label: str
    value: str
    hint: str | None = None


class ServiceRow(BaseModel):
    service: str
    tier: int | None = None
    errPct: float
    reqPerSec: float
    p99Ms: float | None = None
    ready: bool
    fresh: bool
    hitsNext: list[str]
    flag: Level


class PressureRow(BaseModel):
    service: str
    memStallPct: float | None = None
    cpuStallPct: float | None = None
    ioStallPct: float | None = None
    memOfRequestPct: float | None = None
    oomKills: int


class Step(BaseModel):
    text: str
    done: bool


class DarkRow(BaseModel):
    name: str
    silentFor: str


class SignalCount(BaseModel):
    label: str
    count: int


class Link(BaseModel):
    label: str
    url: str


class Handled(BaseModel):
    service: str
    title: str
    at: str
    rca: str | None = None


class Drill(BaseModel):
    facts: list[Fact]
    services: list[ServiceRow] | None = None
    steps: list[Step] | None = None
    note: str | None = None
    pressure: list[PressureRow] | None = None
    dark: list[DarkRow] | None = None
    sparkline: list[float] | None = None
    signals: list[SignalCount] | None = None
    handled: list[Handled] | None = None
    links: list[Link] | None = None


class Indicator(BaseModel):
    id: IndicatorId
    title: str
    question: str
    horizon: str
    state: str
    label: str
    level: Level
    ring: float
    caption: str
    decides: bool
    how: str
    drill: Drill | None = None


class QueueItem(BaseModel):
    id: str
    service: str
    severity: str
    title: str
    openFor: str
    impact: str
    rca: str | None = None
    plan: list[str]
    related: list[str]


class AcceptedItem(BaseModel):
    service: str
    kind: Literal["expected", "noise"]
    reason: str
    title: str | None = None        # the incident it covers, when one is open
    until: str | None = None


class AckIn(BaseModel):
    service: str = Field(min_length=1, max_length=200)      # fleet name, <host>:<service>
    kind: Literal["expected", "noise"] = "expected"
    days: int = Field(default=7, ge=1, le=30)
    reason: str = Field(min_length=1, max_length=200)
    # what is being accepted; worse than this ends the ack. Omitted: read from the fleet's open incident
    severity: Literal["info", "warning", "critical"] | None = None


class Ack(BaseModel):
    service: str
    kind: Literal["expected", "noise"]
    reason: str
    severity: str
    since: str
    until: str


class Rule(BaseModel):
    id: str
    text: str
    leadsTo: str
    fired: bool


class Source(BaseModel):
    mode: Literal["demo", "live"]
    label: str
    tenant: str
    cluster: str | None = None
    connected: bool
    age: str
    now: str


class Decision(BaseModel):
    verdict: Verdict
    word: str
    action: str
    level: Level
    trigger: str
    reason: str
    alsoOpen: list[str]     # other services with an open incident, not named in reason
    dimmed: bool
    dimNote: str | None = None
    rules: list[Rule]


class Event(BaseModel):
    at: str
    kind: Literal["started", "verdict", "indicator", "incident", "ack", "timeline"]
    indicator: str | None = None
    level: Level
    title: str
    detail: str
    incident: str | None = None


class Scenario(BaseModel):
    id: str
    title: str
    story: str


class Outcome(BaseModel):
    verdict: Verdict
    states: dict[str, str]
    reason: str | None = None


class Validation(BaseModel):
    passed: bool
    expected: Outcome
    computed: Outcome


class View(BaseModel):
    source: Source
    decision: Decision
    indicators: list[Indicator]
    queue: list[QueueItem]
    accepted: list[AcceptedItem]
    journal: list[Event]
    journalSource: Literal["live", "scenario"]
    scenario: Scenario | None = None
    validation: Validation | None = None


class OpsService(BaseModel):
    host: str
    service: str
    cluster: str | None = None
    ready: bool
    dark: bool = False              # was seen, says nothing now
    tier: int | None = None
    cpuStallPct: float | None = None
    memStallPct: float | None = None
    ioStallPct: float | None = None
    memOfLimitPct: float | None = None
    oomKills: float | None = None
    incident: str | None = None
    severity: str | None = None
    flapping: bool = False
    accepted: str | None = None     # the reason, when a person accepted it
    calls: list[str] = []           # services on the same host it depends on (compose depends_on, k8s Service names)
    urls: list[str] = []            # public addresses it serves (nginx server_name, Ingress hosts), checked from the hub
    reqPerSec: float | None = None  # users' traffic over the last 5 minutes, where it is measured (Traefik, app vitals)
    errPct: float | None = None     # share of it that failed (5xx)
    p99Ms: float | None = None


class OpsIncident(BaseModel):
    id: str
    host: str
    service: str
    severity: str
    status: str
    title: str
    firstSeen: str | None = None
    resolvedAt: str | None = None
    resolvedBy: str | None = None
    reopens: int
    accepted: str | None = None


class OpsAgent(BaseModel):
    host: str
    connected: bool
    cluster: str | None = None
    lastMessage: str | None = None
    services: int
    dark: int
    error: str | None = None


class OpsBucket(BaseModel):
    t: str
    requests: float                 # everything counted, our own probes included
    errors: float
    traffic: float = 0              # what users sent alone: requests through the ingress or an app's own counters
    trafficErrors: float = 0        # of them, 5xx


class OpsSite(BaseModel):
    url: str
    host: str                       # the agent that reported it
    service: str | None = None
    ok: bool                        # the last check from the internet got an answer below 500
    detail: str | None = None       # "HTTP 200", "the name does not resolve (DNS)", "TLS: ..."
    certDays: float | None = None
    domainDays: float | None = None


class Ops(BaseModel):
    services: list[OpsService]
    incidents: list[OpsIncident]
    agents: list[OpsAgent]
    acks: list[Ack]
    history: list[OpsBucket] = []   # 5-minute buckets of the last day, the whole fleet
    sites: list[OpsSite] = []       # every public address the agents found, as the hub sees it from the internet


class LogLine(BaseModel):
    at: str
    stream: str
    line: str


class Logs(BaseModel):
    selector: str
    lines: list[LogLine]


class LogActivity(BaseModel):
    stepS: int
    start: int              # unix seconds of the first point
    lines: list[float]      # log lines of the whole fleet per step
    errors: list[float]     # of them, lines that read like an error


class NoisyStream(BaseModel):
    host: str               # Loki labels, not tracker names
    service: str
    errors: float           # error lines in the last hour


class LogStats(BaseModel):
    available: bool
    reason: str | None = None
    activity: LogActivity | None = None
    noisiest: list[NoisyStream]


class ScenarioListItem(BaseModel):
    id: str
    title: str
    file: str
    expected: Verdict
    actual: Verdict
    passed: bool


class FleetItem(BaseModel):
    tenant: str
    verdict: Verdict
    word: str
    level: Level
    reason: str


class Health(BaseModel):
    status: Literal["ok"]
    live: bool
