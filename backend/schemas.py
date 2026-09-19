"""Response models of the API.

presentation.py builds plain dicts so that it, the engine and the static export
run on the standard library alone. These models are the contract on top: FastAPI
validates every response against them, publishes them as OpenAPI, and the
frontend types in frontend/src/api.gen.ts are generated from that document
(`npm run gen:types`), so the two sides cannot drift silently.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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
    dimmed: bool
    dimNote: str | None = None
    rules: list[Rule]


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
    scenario: Scenario | None = None
    validation: Validation | None = None


class ScenarioListItem(BaseModel):
    id: str
    title: str
    file: str
    expected: Verdict
    actual: Verdict
    passed: bool


class Health(BaseModel):
    status: Literal["ok"]
    live: bool
