"""Turn an engine result into the view model the tracker screen renders.

The engine (engine.py) decides. This module only words the decision for a
human: state labels, one-line captions, ring fill, the reason line under the
verdict, the drill-in content, and the incident queue. No thresholds live
here. Raw values (error %, stall %, p99) appear only inside `drill`.
"""
from __future__ import annotations

from datetime import datetime

FRESH_S = 300
DASH = "—"
RECENT_BUCKETS = 24

VERDICTS = {
    "all_clear": {"word": "ALL CLEAR", "action": "Nothing to do", "level": "good"},
    "schedule": {"word": "SCHEDULE", "action": "Plan the work, not today", "level": "warn"},
    "act_now": {"word": "ACT NOW", "action": "This needs a human today", "level": "bad"},
    "blind": {"word": "BLIND", "action": "Fix data collection first", "level": "muted"},
}

INDICATORS = {
    "users": {"title": "Users now", "question": "Are people hurting right now?", "horizon": "now"},
    "forecast": {"title": "What's brewing", "question": "What is coming in the next hours?", "horizon": "next hours"},
    "trust": {"title": "Can we trust it", "question": "Is this picture complete and fresh?", "horizon": "now"},
    "day": {"title": "How the day went", "question": "Did anything change since yesterday?", "horizon": "last 24 h"},
}

STATE_LABELS = {
    "ok": ("Fine", "good"), "degraded": ("Degraded", "warn"), "broken": ("Broken", "bad"),
    "clear": ("Clear", "good"), "pressure": ("Pressure", "warn"), "brewing": ("Brewing", "warn"),
    "full": ("Full", "good"), "partial": ("Partial", "warn"), "blind": ("Blind", "bad"),
    "quiet": ("Quiet", "good"), "settled": ("Settled", "good"), "regressed": ("Regressed", "warn"),
    "unknown": (DASH, "muted"),
}

RULES = [
    ("trust_blind", "The data cannot be trusted", "BLIND"),
    ("users_broken", "Users are broken right now", "ACT NOW"),
    ("critical_incident", "A critical incident is open", "ACT NOW"),
    ("forecast_imminent", "A failure is brewing on the user path with under 30 min of warning", "ACT NOW"),
    ("users_escalated", "Users are degraded in a service on the user path", "ACT NOW"),
    ("users_degraded", "Users are degraded", "SCHEDULE"),
    ("forecast_risk", "Something is brewing", "SCHEDULE"),
    ("day_regressed", "The day got worse than the norm", "SCHEDULE"),
    ("warning_incident", "A warning incident is open", "SCHEDULE"),
    ("trust_partial", "Part of the fleet is not visible", "SCHEDULE"),
    ("calm", "None of the above", "ALL CLEAR"),
]


# ------------------------------------------------------------------ helpers ---

def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def tenant_block(data: dict) -> dict:
    return data["status"].get("tenantStats", {}).get("tenants", {}).get(data["tenant"], {})


def node_of(data: dict, name: str) -> dict:
    return next((n for n in data["graph"]["nodes"] if n["name"] == name), {})


def app_of(data: dict, name: str) -> dict:
    return next((a for a in data["applications"] if a["name"] == name), {})


def best_precursor(data: dict) -> dict | None:
    matches = data["analytics"].get("precursorMatches", [])
    return max(matches, key=lambda m: m["confidence"], default=None)


def age_text(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600)} h"


def times_word(ratio: float) -> str:
    if ratio < 2.5:
        return "twice"
    if ratio < 3.5:
        return "three times"
    return f"{round(ratio)}x"


def bucket_err(bucket: dict) -> float:
    return 100 * bucket["requestErrors"] / bucket["requests"] if bucket["requests"] else 0.0


def day_facts(data: dict, info: dict) -> dict:
    """Peak time and start of the current elevated run, read from signalsHistory."""
    history = tenant_block(data).get("signalsHistory", [])
    base = info.get("errBase") or 0
    if not history or not base:
        return {}
    # a spike is named by when it started, not by its tallest bucket
    peak_index = max(range(len(history)), key=lambda i: bucket_err(history[i]))
    while peak_index > 0 and bucket_err(history[peak_index - 1]) > 1.5 * base:
        peak_index -= 1
    peak = history[peak_index]
    since = None
    for bucket in reversed(history):
        if bucket_err(bucket) > 1.5 * base:
            since = bucket
        else:
            break
    return {
        "peakAt": parse(peak["t"]).strftime("%H:%M"),
        "since": parse(since["t"]).strftime("%H:%M") if since else None,
    }


def oldest_data_age(data: dict) -> float | None:
    now = parse(data["now"]).timestamp()
    stamps = [a["golden"][k] for a in data["applications"] for k in a["golden"] if k.endswith("AsOfUnix")]
    return now - min(stamps) if stamps else None


def dark_services(data: dict) -> list[dict]:
    now = parse(data["now"])
    out = []
    for item in tenant_block(data).get("darkServices", []):
        silent = (now - parse(item["lastEventAt"])).total_seconds()
        out.append({"name": item["name"], "silentFor": age_text(silent), "silentSeconds": silent})
    return out


def affected_services(data: dict) -> list[str]:
    now = parse(data["now"]).timestamp()
    return [a["name"] for a in data["applications"]
            if a["golden"].get("errPct", 0) >= 1 and now - a["golden"].get("rateAsOfUnix", 0) <= FRESH_S]


def noisy_log_source(data: dict) -> str | None:
    """A log storm with no request impact: worth one calm sentence, never an alarm."""
    by_type = tenant_block(data).get("signalsByType", {})
    if by_type.get("log", 0) < 1000 or by_type.get("red", 0) > 0:
        return None
    sources = tenant_block(data).get("topSignalSources", [])
    logs = [s for s in sources if s.get("type") == "log"]
    return logs[0]["service"] if logs else "one service"


# ----------------------------------------------------------------- captions ---

def users_caption(data: dict, state: str, info: dict) -> str:
    if state == "unknown":
        return "no fresh traffic data"
    if state == "broken":
        broken = info.get("tier1Broken") or info.get("affected") or ["a service"]
        return f"{broken[0]} is down"
    if state == "degraded":
        n = len(info.get("affected", []))
        return f"{info['failingShare']}% of requests failing in {plural(n, 'service')}"
    return "all requests are going through"


def forecast_caption(data: dict, state: str, info: dict) -> str:
    if state == "unknown":
        return "no forecast without data"
    service = info.get("service")
    match = best_precursor(data)
    if info.get("downgraded") and match:
        return f"agent suspects {match['service']}, but it is wrong more often than right"
    if state == "brewing" and info.get("pressure"):
        app = app_of(data, info["pressure"][0])
        ooms = app.get("golden", {}).get("oomKills", 0)
        tail = "OOM kills have started" if ooms else "no OOM kill yet"
        return f"{info['pressure'][0]}: memory is saturating, {tail}"
    if state == "brewing" and match:
        lead = f", usually ~{info['leadMin']} min of warning" if info.get("leadMin") else ""
        return f"{match['matchedSteps']} of {match['totalSteps']} steps to a {service} failure{lead}"
    if state == "pressure":
        return f"some pressure in {service}, there is time" if service else "some resource pressure, there is time"
    return "nothing is brewing"


def trust_caption(data: dict, state: str, info: dict) -> str:
    if state == "blind":
        if info.get("disconnectedMinutes") is not None:
            return f"cluster agent disconnected for {info['disconnectedMinutes']} min"
        return "not enough of the fleet is reporting"
    services = tenant_block(data).get("services", 0)
    if state == "partial":
        dark = dark_services(data)
        if dark:
            longest = max(dark, key=lambda d: d["silentSeconds"])
            return f"{join_names([d['name'] for d in dark])} silent for {longest['silentFor']}"
        if info.get("unmapped"):
            return f"{plural(info['unmapped'], 'service')} not in the service graph"
        return f"fresh data from only {info.get('freshShare')}% of traffic"
    age = oldest_data_age(data)
    return f"seeing all {services} services, data is {age_text(age)} old" if age is not None else f"seeing all {services} services"


def day_caption(data: dict, state: str, info: dict) -> str:
    if state == "unknown":
        return "not enough history yet"
    facts = day_facts(data, info)
    tenant = tenant_block(data)
    if state == "regressed":
        ratio = info["errRecent"] / info["errBase"] if info.get("errBase") else 0
        if ratio > 2 and facts.get("since"):
            return f"errors {times_word(ratio)} the norm since {facts['since']}"
        if info.get("repeatRate", 0) > 20:
            return f"{info['repeatRate']}% of incidents keep coming back"
        return f"{plural(info['incidentsToday'], 'incident')} today, more than usual"
    if state == "settled":
        return f"{facts.get('peakAt', 'earlier')} spike settled, the agent closed it on its own"
    if tenant.get("incidents", {}).get("openNow", 0):
        return "quiet until the last few minutes"
    closed = [i for i in data["incidents"]["incidents"] if i.get("resolvedBy") == "agent"]
    if closed:
        return f"quiet day, the agent closed {len(closed)} on its own"
    noise = tenant.get("events", {}).get("noise")
    return "quiet day, nothing reached a human" if noise else "quiet day"


CAPTIONS = {"users": users_caption, "forecast": forecast_caption, "trust": trust_caption, "day": day_caption}


# -------------------------------------------------------------- reason line ---

def human_reason(data: dict, result: dict) -> str:
    trigger, detail, states = result["trigger"], result["detail"], result["states"]

    if trigger == "trust_blind":
        return trust_caption(data, "blind", detail["trust"]) + ", the fleet is not visible"

    if trigger in ("users_broken", "critical_incident"):
        info = detail.get("users", {})
        open_incidents = [i for i in data["incidents"]["incidents"] if i.get("status") == "open"]
        service = (info.get("tier1Broken") or [i["service"] for i in open_incidents] or info.get("affected") or ["a service"])[0]
        callers = node_of(data, service).get("calledBy", [])
        head = f"{service} is down" if trigger == "users_broken" else f"{service}: critical incident open"
        return head + (f", {plural(len(callers), 'more service')} will be hit" if callers else "")

    if trigger == "forecast_imminent":
        info, match = detail["forecast"], best_precursor(data)
        return (f"{info['service']}: agent sees {match['matchedSteps']} of {match['totalSteps']} steps to a failure, "
                f"usually ~{info['leadMin']} min of warning")

    if trigger in ("users_escalated", "users_degraded"):
        info = detail["users"]
        return f"{info['failingShare']}% of requests failing in {join_names(info['affected'])}"

    if trigger == "forecast_risk":
        return forecast_caption(data, "brewing", detail["forecast"])

    if trigger == "day_regressed":
        names = affected_services(data)
        return day_caption(data, "regressed", detail["day"]) + (f" in {join_names(names)}" if names else "")

    if trigger == "warning_incident":
        open_incidents = [i for i in data["incidents"]["incidents"] if i.get("status") == "open"]
        return f"{open_incidents[0]['service']}: {open_incidents[0]['title']}" if open_incidents else "a warning incident is open"

    if trigger == "trust_partial":
        caption = trust_caption(data, "partial", detail["trust"])
        return caption + (": healthy or dead, unknown" if dark_services(data) else "")

    # calm: say the most useful quiet-day thing we know
    if detail["forecast"].get("downgraded"):
        match = best_precursor(data)
        return f"all normal; agent suspects {match['service']} but is wrong more often than right"
    if states["day"] == "settled":
        return day_caption(data, "settled", detail["day"])
    noisy = noisy_log_source(data)
    if noisy:
        return f"{noisy} is noisy in logs, users are not affected"
    return "all normal, nothing happened in the last day"


# --------------------------------------------------------------------- rings ---

def ring_value(key: str, state: str, info: dict) -> float:
    if state == "unknown":
        return 0.0
    if key == "users":
        return clamp(1 - info.get("failingShare", 0) / 5, 0.06)
    if key == "forecast":
        if info.get("pressure"):
            return 0.35
        return clamp(1 - info.get("precursorLevel", 0), 0.06)
    if key == "trust":
        if state == "blind":
            return 0.06
        return clamp(info.get("coverage", 0) / 100 * info.get("freshShare", 0) / 100, 0.06)
    if key == "day":
        base = info.get("errBase") or 0
        ratio = info.get("errRecent", 0) / base if base else 1
        return clamp(1 - (ratio - 1) / 2, 0.06)
    return 0.0


# ------------------------------------------------------------------ drill-in ---

def fact(label: str, value, hint: str | None = None) -> dict:
    return {"label": label, "value": str(value), **({"hint": hint} if hint else {})}


def users_drill(data: dict, info: dict) -> dict:
    now = parse(data["now"]).timestamp()
    rows = []
    for app in data["applications"]:
        g = app["golden"]
        if "reqPerSec" not in g:
            continue
        node = node_of(data, app["name"])
        rows.append({
            "service": app["name"], "tier": node.get("tier"),
            "errPct": g["errPct"], "reqPerSec": g["reqPerSec"], "p99Ms": g.get("p99Ms"),
            "ready": app.get("ready", True), "fresh": now - g.get("rateAsOfUnix", 0) <= FRESH_S,
            "hitsNext": node.get("calledBy", []),
            "flag": "bad" if g["errPct"] >= 5 or not app.get("ready", True) else "warn" if g["errPct"] >= 1 else "good",
        })
    rows.sort(key=lambda r: (-r["errPct"], -r["reqPerSec"]))
    return {
        "facts": [fact("Requests failing fleet-wide", f"{info.get('failingShare', DASH)}%", "weighted by traffic"),
                  fact("Services with errors above 1%", len(info.get("affected", []))),
                  fact("Threshold", "0.5% schedule, 5% act now")],
        "services": rows[:8],
    }


def forecast_drill(data: dict, info: dict) -> dict:
    match = best_precursor(data)
    tenant = tenant_block(data)
    hits, misses = tenant.get("predictionHits", 0), tenant.get("predictionMisses", 0)
    facts = []
    if hits + misses:
        facts.append(fact("Agent track record", f"{hits} right, {misses} wrong", f"{tenant.get('predictionPrecisionPct')}% precision"))
    if info.get("leadMin"):
        facts.append(fact("Usual warning time", f"~{info['leadMin']} min"))
    out: dict = {"facts": facts}
    if match:
        facts.insert(0, fact("Pattern", match.get("patternId", DASH), f"confidence {match['confidence']:.2f}"))
        out["steps"] = ([{"text": s, "done": True} for s in match.get("matched", [])]
                        + [{"text": s, "done": False} for s in match.get("remaining", [])])
        if info.get("downgraded"):
            out["note"] = "Shown dimmed: below 60% precision a forecast cannot move the verdict."
    pressure = []
    for app in data["applications"]:
        g = app["golden"]
        worst = max(g.get("memPsiPct", 0), g.get("cpuPsiPct", 0), g.get("ioPsiPct", 0))
        if worst >= 1 or g.get("oomKills", 0):
            pressure.append({"service": app["name"], "memStallPct": g.get("memPsiPct"), "cpuStallPct": g.get("cpuPsiPct"),
                             "ioStallPct": g.get("ioPsiPct"), "memOfRequestPct": g.get("memReqPct"), "oomKills": g.get("oomKills", 0)})
    if pressure:
        out["pressure"] = pressure
    return out


def trust_drill(data: dict, info: dict) -> dict:
    tenant = tenant_block(data)
    agent = data["status"].get("clusterAgentStats", {}).get(data["tenant"], {})
    now = parse(data["now"]).timestamp()
    age = oldest_data_age(data)
    events = tenant.get("events", {})
    facts = [
        fact("Cluster agent", "connected" if agent.get("connected") else "disconnected",
             f"last message {age_text(now - agent.get('lastMessageUnix', now))} ago"),
        fact("Services reporting", f"{tenant.get('services', 0) - tenant.get('servicesDark', 0)} of {tenant.get('services', 0)}",
             f"{tenant.get('serviceCoveragePct', DASH)}% coverage"),
        fact("Oldest data on screen", age_text(age) if age is not None else DASH, "fresh means under 5 min"),
        fact("Not in the service graph", data["status"].get("unmappedServices", 0)),
    ]
    if events:
        facts.append(fact("Filtered as noise by the agent", f"{events.get('noise', 0):,}",
                          f"{events.get('signal', 0)} signals, {events.get('incident', 0)} incidents"))
    return {"facts": facts, "dark": dark_services(data)}


def day_drill(data: dict, info: dict) -> dict:
    tenant = tenant_block(data)
    history = tenant.get("signalsHistory", [])
    points = []
    for i in range(0, len(history), 3):
        chunk = history[i:i + 3]
        req = sum(b["requests"] for b in chunk)
        points.append(round(100 * sum(b["requestErrors"] for b in chunk) / req, 3) if req else 0)
    facts = [
        fact("Errors, last 2 h", f"{info.get('errRecent', DASH)}%", f"norm {info.get('errBase', DASH)}%"),
        fact("Incidents today", info.get("incidentsToday", 0), f"usual {info.get('normPerDay', DASH)} a day"),
    ]
    if tenant.get("sampledIncidents"):
        facts.append(fact("Closed by the agent alone", f"{tenant.get('autoResolvedPct')}%"))
        facts.append(fact("Coming back", f"{tenant.get('repeatRatePct')}%", "above 20% means schedule root-cause work"))
    by_type = tenant.get("signalsByType", {})
    names = {"log": "Logs", "red": "Requests", "use": "Resources", "k8s": "Platform"}
    return {
        "facts": facts,
        "sparkline": points,
        "recentFrom": len(points) - RECENT_BUCKETS // 3,
        "signals": [{"label": names.get(k, k), "count": v} for k, v in by_type.items()],
        "handled": [{"service": i["service"], "title": i["title"], "at": parse(i["firstSeen"]).strftime("%H:%M"), "rca": i.get("rca")}
                    for i in data["incidents"]["incidents"] if i.get("resolvedBy") == "agent"],
    }


DRILLS = {"users": users_drill, "forecast": forecast_drill, "trust": trust_drill, "day": day_drill}


# ------------------------------------------------------------------- blocks ---

def indicator_cards(data: dict, result: dict) -> list[dict]:
    cards = []
    blind = result["verdict"] == "blind"
    for key, meta in INDICATORS.items():
        state = result["states"][key]
        info = result["detail"].get(key, {})
        label, level = STATE_LABELS[state]
        dimmed = key == "forecast" and bool(info.get("downgraded"))
        card = {
            "id": key, **meta, "state": state, "label": label,
            "level": "muted" if dimmed else level,
            "ring": ring_value(key, state, info),
            # blind: the other three are not "fine" and not "bad", they are unknown
            "caption": "greyed out until data is back" if blind and key != "trust" else CAPTIONS[key](data, state, info),
            "decides": key == result["trigger"].split("_")[0],
        }
        if not (blind and key != "trust"):
            card["drill"] = DRILLS[key](data, info)
        cards.append(card)
    return cards


def incident_queue(data: dict) -> list[dict]:
    now = parse(data["now"])
    order = {"critical": 0, "warning": 1, "info": 2}
    queue = []
    for inc in data["incidents"]["incidents"]:
        if inc.get("status") != "open":
            continue
        callers = node_of(data, inc["service"]).get("calledBy", [])
        queue.append({
            "id": inc["id"], "service": inc["service"], "severity": inc["severity"], "title": inc["title"],
            "openFor": age_text((now - parse(inc["firstSeen"])).total_seconds()),
            "impact": f"hits next: {join_names(callers)}" if callers else "no downstream callers",
            "rca": inc.get("rca"), "plan": inc.get("investigationPlan", []), "related": inc.get("relatedEvents", []),
            "_rank": (order.get(inc["severity"], 3), -inc.get("blastRadius", 0)),
        })
    queue.sort(key=lambda q: q["_rank"])
    for q in queue:
        q.pop("_rank")
    return queue


def source_block(data: dict, mode: str) -> dict:
    agent = data["status"].get("clusterAgentStats", {}).get(data["tenant"], {})
    now = parse(data["now"]).timestamp()
    return {
        "mode": mode,
        "label": "Demo data" if mode == "demo" else "Live",
        "tenant": data["tenant"],
        "cluster": agent.get("cluster"),
        "connected": bool(agent.get("connected")),
        "age": age_text(now - agent.get("lastMessageUnix", now)),
        "now": data["now"],
    }


def build_view(data: dict, result: dict, mode: str = "demo") -> dict:
    meta = VERDICTS[result["verdict"]]
    view = {
        "source": source_block(data, mode),
        "decision": {
            "verdict": result["verdict"], **meta,
            "trigger": result["trigger"],
            "reason": human_reason(data, result),
            "dimmed": result["states"]["trust"] == "partial",
            "rules": [{"id": rid, "text": text, "leadsTo": leads, "fired": rid == result["trigger"]}
                      for rid, text, leads in RULES],
        },
        "indicators": indicator_cards(data, result),
        "queue": incident_queue(data),
    }
    if "expected" in data:
        expected = data["expected"]
        view["scenario"] = {"id": data["scenario"], "title": data["title"], "story": data["story"]}
        view["validation"] = {
            "passed": result["verdict"] == expected["verdict"] and result["states"] == expected["states"],
            "expected": {"verdict": expected["verdict"], "states": expected["states"], "reason": expected.get("reason")},
            "computed": {"verdict": result["verdict"], "states": result["states"]},
        }
    return view
