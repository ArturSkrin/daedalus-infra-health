from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend import acks, external, journal, live, logs, notify, ops
from backend.engine import verdict
from backend.fleet import FLEET
from backend.presentation import build_view
from backend.repository import ScenarioNotFound, list_scenarios, load_scenario
from backend.schemas import Ack, AckIn, Event, FleetItem, Health, Logs, LogStats, Ops, ScenarioListItem, View

log = logging.getLogger("daedalus")
JOURNAL_POLL_S = int(os.environ.get("JOURNAL_POLL_S", "20"))


def observe_live(tenant: str | None = None) -> dict:
    """Fetch, decide, word, and write to the journal whatever changed. One path for the endpoint and the watcher."""
    data = live.load_live(tenant)
    data = acks.apply(data, prefix="" if data["tenant"] == FLEET else f"{data['tenant']}:")
    result = verdict(data)
    view = build_view(data, result, mode="live", journal=[])
    fresh = journal.observe(data["tenant"], view, at=data["now"])
    # one push per change: from the fleet's journal when there are agents (each tenant's own would repeat it)
    if data["tenant"] == FLEET or not live.agents():
        notify.send(fresh)
    view["journal"] = journal.events(data["tenant"])
    return view


def _watch(stop: threading.Event) -> None:
    # The journal must not depend on somebody having the page open: a change at 03:00 is exactly the one
    # people want to read about at 09:00. The cache in live.py keeps this from doubling the load on the core.
    while not stop.is_set():
        # the fleet summary first: its journal is the one that says "something somewhere changed"
        for tenant in ([FLEET] if live.agents() else []) + live.tenants():
            try:
                observe_live(tenant)
            except live.LiveUnavailable as error:
                log.warning("journal watcher (%s): %s", tenant, error)
            except Exception:
                log.exception("journal watcher failed (%s)", tenant)
        stop.wait(JOURNAL_POLL_S)


def _refresh_addresses() -> None:
    """Read every agent once, so the outside checks know the addresses each one reports right now."""
    for tenant in live.tenants():
        with contextlib.suppress(live.LiveUnavailable):     # a silent agent keeps the addresses it reported last
            live.load_live(tenant)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = threading.Event()
    if live.configured():
        threading.Thread(target=_watch, args=(stop,), name="journal-watcher", daemon=True).start()
        threading.Thread(target=external.watch, args=(stop, _refresh_addresses), name="outside-checks", daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Daedalus Infra Health", version="0.4.0", lifespan=lifespan)

# Read-only API with no credentials. Behind nginx the frontend is same-origin;
# the open CORS policy only matters for `npm run dev` against a local backend.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])


def _scenario_or_404(scenario_id: str) -> dict:
    try:
        return load_scenario(scenario_id)
    except ScenarioNotFound:
        raise HTTPException(status_code=404, detail="Scenario not found") from None


@app.get("/api/health", response_model=Health)
def health() -> dict:
    return {"status": "ok", "live": live.configured()}


@app.get("/api/scenarios", response_model=list[ScenarioListItem])
def scenarios() -> list[dict]:
    response = []
    for item in list_scenarios():
        data = load_scenario(item["id"])
        result = verdict(data)
        expected = data["expected"]
        response.append({
            **item,
            "actual": result["verdict"],
            "passed": result["verdict"] == expected["verdict"] and result["states"] == expected["states"],
        })
    return response


@app.get("/api/scenarios/{scenario_id}", response_model=View, response_model_exclude_none=True)
def scenario(scenario_id: str) -> dict:
    data = _scenario_or_404(scenario_id)
    return build_view(data, verdict(data), mode="demo")


@app.get("/api/scenarios/{scenario_id}/raw")
def scenario_raw(scenario_id: str) -> dict:
    """The mock Triage responses behind a scenario, exactly as the engine receives them."""
    return _scenario_or_404(scenario_id)


@app.get("/api/live", response_model=View, response_model_exclude_none=True)
def live_view(tenant: str | None = None) -> dict:
    """Same view model, computed from a real Triage core instead of a mock file."""
    try:
        return observe_live(tenant)
    except live.LiveUnavailable as error:
        raise HTTPException(status_code=503, detail=f"Live data unavailable: {error}") from None


@app.get("/api/fleet", response_model=list[FleetItem])
def fleet() -> list[dict]:
    """One line per tenant: the word and why. An agent that does not answer is BLIND, never left out."""
    if not live.configured():
        return []
    items = []
    for tenant in live.tenants():
        try:
            view = observe_live(tenant)
        except live.LiveUnavailable as error:
            items.append({"tenant": tenant or "live", "verdict": "blind", "word": "BLIND", "level": "bad", "reason": str(error)})
            continue
        decision = view["decision"]
        items.append({"tenant": view["source"]["tenant"], "verdict": decision["verdict"], "word": decision["word"],
                      "level": decision["level"], "reason": decision["reason"]})
    return items


@app.get("/api/acks", response_model=list[Ack])
def list_acks() -> list[dict]:
    return [acks.public(a) for a in acks.listing()]


@app.post("/api/acks", response_model=Ack)
def add_ack(body: AckIn) -> dict:
    """Accept one service for a while. Its severity now is the line: getting worse than that ends the ack."""
    severity = body.severity or "warning"
    if not body.severity:
        try:
            opened = [i for i in (live.load_live(FLEET).get("incidents") or {}).get("incidents") or []
                      if i.get("service") == body.service and i.get("status") == "open"]
            severity = "critical" if any(i.get("severity") == "critical" for i in opened) else severity
        except live.LiveUnavailable:
            pass
    try:
        return acks.public(acks.add(body.service, body.kind, body.days, body.reason, severity))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.delete("/api/acks/{service:path}", status_code=204)
def remove_ack(service: str) -> None:
    if not acks.remove(service):
        raise HTTPException(status_code=404, detail="No ack for this service")


@app.get("/api/ops", response_model=Ops)
def ops_view(scenario: str | None = None) -> dict:
    """The admin screen: every service, incident and agent of the fleet as rows, with no verdict on top.
    ?scenario= shows a demo scenario instead, so the screen can be looked at without agents."""
    if scenario:
        return ops.snapshot(_scenario_or_404(scenario))
    if not live.configured():
        raise HTTPException(status_code=503, detail="Live data unavailable: live mode is not configured")
    return ops.snapshot()


_logstats: dict = {}


@app.get("/api/logstats", response_model=LogStats)
def log_stats(scenario: str | None = None) -> dict:
    """The fleet's log activity over the last 24 h and the streams writing the most errors now. Cached for a minute.
    ?scenario= stands the scenario's own request history in for the logs, to look at the screen without Loki."""
    if scenario:
        block = _scenario_or_404(scenario)
        tenant = block["status"]["tenantStats"]["tenants"][block["tenant"]]
        history = (tenant.get("signalsHistory") or [])[-288:]
        pairs = [history[i:i + 2] for i in range(0, len(history), 2)]        # 5-minute buckets into 10-minute ones
        start = int(time.time()) // 600 * 600 - (len(pairs) - 1) * 600
        return {"available": True, "reason": "demo: the scenario's requests stand in for log lines",
                "activity": {"stepS": 600, "start": start, "lines": [sum(b.get("requests") or 0 for b in p) for p in pairs],
                             "errors": [sum(b.get("requestErrors") or 0 for b in p) for p in pairs]},
                "noisiest": [{"host": block["tenant"], "service": a["name"], "errors": round(a["golden"]["errPct"] * 10, 1)}
                             for a in block.get("applications") or [] if (a.get("golden") or {}).get("errPct", 0) >= 0.5]}
    if _logstats and time.monotonic() - _logstats["at"] < 60:
        return _logstats["value"]
    try:
        value = {"available": True, "activity": logs.activity(), "noisiest": logs.noisiest()}
    except logs.LogsUnavailable as error:
        value = {"available": False, "reason": str(error), "activity": None, "noisiest": []}
    _logstats.update(at=time.monotonic(), value=value)
    return value


@app.get("/api/logs", response_model=Logs)
def service_logs(service: str = "", limit: int = 200, loki_host: str = "", loki_service: str = "") -> dict:
    """Recent lines of one fleet service (<host>:<service>) from Loki, newest first. loki_host and loki_service
    name a Loki stream by its own labels instead, as /api/logstats lists them."""
    if loki_host and loki_service:
        try:
            return logs.stream(loki_host, loki_service, limit=max(1, min(limit, 1000)))
        except logs.LogsUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from None
    host, _, name = service.partition(":")
    if not host or not name:
        raise HTTPException(status_code=422, detail="service must be <host>:<service>")
    try:
        cluster = ((live.load_live(host).get("status") or {}).get("clusterAgentStats") or {}).get(host, {}).get("cluster")
    except live.LiveUnavailable:
        cluster = None
    try:
        return logs.recent(host, name, cluster, limit=max(1, min(limit, 1000)))
    except logs.LogsUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@app.get("/api/live/journal", response_model=list[Event], response_model_exclude_none=True)
def live_journal(tenant: str | None = None, limit: int = 200) -> list[dict]:
    """Every recorded change for the live tenant, newest first."""
    name = tenant or (FLEET if live.agents() else os.environ.get("TRIAGE_TENANT"))
    if not name:
        try:
            name = live.load_live(None)["tenant"]
        except live.LiveUnavailable as error:
            raise HTTPException(status_code=503, detail=f"Live data unavailable: {error}") from None
    return journal.events(name, limit=max(1, min(limit, 500)))
