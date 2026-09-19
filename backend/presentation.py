"""Turn an engine result into the view model the tracker screen renders.

engine.py decides; this module only words the decision for a human: state
labels, one-line captions, ring fill, the reason line under the verdict, the
drill-in content, and the incident queue. It reads facts from the engine result
and display data from the Bundle. It holds no thresholds and never re-derives a
decision. Raw values (error %, stall %, p99) appear only inside `drill`.
"""
from __future__ import annotations

from backend import thresholds as T
from backend.bundle import Bundle, normalize

DASH = "—"

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
    ("forecast_imminent", f"A failure is brewing on the user path with under {T.ACT_NOW_LEAD_MS // 60000} min of warning", "ACT NOW"),
    ("users_escalated", "Users are degraded in a service on the user path", "ACT NOW"),
    ("users_degraded", "Users are degraded", "SCHEDULE"),
    ("forecast_risk", "Something is brewing", "SCHEDULE"),
    ("day_regressed", "The day got worse than the norm", "SCHEDULE"),
    ("warning_incident", "A warning incident is open", "SCHEDULE"),
    ("trust_partial", "Part of the fleet is not visible", "SCHEDULE"),
    ("calm_unverified", "Nothing calls for work, but one vital could not be judged", "ALL CLEAR, dimmed"),
    ("calm", "None of the above", "ALL CLEAR"),
]

DIM_NOTES = {
    "partial": "Part of the fleet is not visible, so this is a floor, not a guarantee.",
    "unverified": "One vital could not be judged yet, so this is a floor, not a guarantee.",
}


# ------------------------------------------------------------------ helpers ---

def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def age_text(seconds: float | None) -> str:
    if seconds is None:
        return DASH
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


def shown(value, suffix: str = "") -> str:
    """A measured value, or a dash. Zero is a value; None is not."""
    return DASH if value is None else f"{value:g}{suffix}" if isinstance(value, float) else f"{value}{suffix}"


def oldest_data_age(b: Bundle) -> float | None:
    ages = [a for s in b.services.values() for a in ((s.rate.age_s if s.rate else None), (s.saturation.age_s if s.saturation else None))
            if a is not None]
    return max(ages) if ages else None


def open_incidents(b: Bundle) -> list:
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted((i for i in b.incidents if i.is_open), key=lambda i: (order.get(i.severity, 3), -i.blast_radius))


def noisy_log_source(b: Bundle) -> str | None:
    """A log storm with no request impact: worth one calm sentence, never an alarm."""
    if b.signals_by_type.get("log", 0) < 1000 or b.signals_by_type.get("red", 0) > 0:
        return None
    logs = [s for s in b.top_signal_sources if s.get("type") == "log" and isinstance(s.get("service"), str)]
    return logs[0]["service"] if logs else "one service"


# ----------------------------------------------------------------- captions ---

def users_caption(b: Bundle, state: str, info: dict) -> str:
    if state == "unknown":
        return "no fresh traffic data"
    if state == "broken":
        return f"{info.get('service') or 'a service'} is down"
    if state == "degraded":
        return f"{info['failingShare']}% of requests failing in {plural(len(info['affected']), 'service')}"
    return "all requests are going through"


def forecast_caption(b: Bundle, state: str, info: dict) -> str:
    if state == "unknown":
        return "no fresh resource data, no forecast"
    match, service = info.get("match"), info.get("service")
    if info.get("downgraded"):
        return f"agent suspects {match['service']}, but it is wrong more often than right"
    if state == "brewing" and info.get("pressure"):
        tail = "OOM kills have started" if info.get("oomStarted") else "no OOM kill yet"
        return f"{service}: memory is saturating, {tail}"
    if state == "brewing" and info.get("stalled"):
        return f"{service}: {info['stalledResource']} stall is slowing it down"
    if state == "brewing" and match and info.get("unproven"):
        return (f"{match['matched']} of {match['total']} steps to a {service} failure, "
                "the agent's track record is too short to call it urgent")
    if state == "brewing" and match:
        lead = f", usually ~{info['leadMin']} min of warning" if info.get("leadMin") else ""
        return f"{match['matched']} of {match['total']} steps to a {service} failure{lead}"
    if state == "pressure":
        return f"some pressure in {service}, there is time" if service else "some resource pressure, there is time"
    return "nothing is brewing"


TRUST_REASONS = {
    "tenant_missing": "the core does not report this tenant",
    "no_services": "the core reports no services for this tenant",
    "coverage_unknown": "the core does not say how much of the fleet it sees",
    "no_fresh_data": "no fresh data from any service",
    "low_coverage": "not enough of the fleet is reporting",
    "unmapped_services": "some services are not in the service graph",
    "unclassified_events": "the agent could not classify a large share of events, so its silence is not proof of calm",
    "stale_traffic": "traffic data is stale for part of the fleet",
    "stale_resources": "resource pressure data is stale, so the forecast is blind",
    "no_resource_data": "resource pressure is not collected, so the forecast is blind",
}


def trust_caption(b: Bundle, state: str, info: dict) -> str:
    reasons = info.get("reasons", [])
    if "agent_disconnected" in reasons:
        minutes = info.get("disconnectedMinutes")
        return f"cluster agent disconnected for {minutes} min" if minutes is not None else "cluster agent disconnected"
    if "dark_services" in reasons:
        if b.dark:
            longest = max((d.silent_s or 0) for d in b.dark)
            return f"{join_names([d.name for d in b.dark])} silent for {age_text(longest)}"
        return f"{plural(info['dark'], 'service')} went silent"
    if reasons:
        if reasons[0] == "unclassified_events":
            return f"agent could not classify {info['unclassifiedShare']:g}% of events"
        if reasons[0] == "unmapped_services":
            return f"{plural(info['unmapped'], 'service')} not in the service graph"
        if reasons[0] == "stale_traffic":
            return f"fresh data from only {info['freshShare']:g}% of traffic"
        return TRUST_REASONS.get(reasons[0], "part of the picture is missing")
    age = oldest_data_age(b)
    seeing = f"seeing all {b.services_total} services"
    return f"{seeing}, data is {age_text(age)} old" if age is not None else seeing


def day_caption(b: Bundle, state: str, info: dict) -> str:
    if state == "unknown":
        if info.get("why") == "short_history":
            return f"only {info['historyHours']:g} h of history so far"
        return "too little traffic to judge the day"
    if state == "regressed":
        because = info.get("because")
        if because == "errors" and info.get("since"):
            return f"errors {times_word(info['ratio'])} the norm since {info['since']}"
        if because == "repeats":
            return f"{info['repeatRate']:g}% of incidents keep coming back"
        return f"{plural(info['incidentsToday'], 'incident')} today, more than usual"
    if state == "settled":
        closed_by_agent = any(i.resolved_by == "agent" for i in b.incidents)
        tail = "the agent closed it on its own" if closed_by_agent else "it never needed an incident"
        return f"{info.get('spikeAt') or 'earlier'} spike settled, {tail}"
    if info.get("openNow"):
        return "quiet until the last few minutes"
    closed = [i for i in b.incidents if i.resolved_by == "agent"]
    if closed:
        return f"quiet day, the agent closed {len(closed)} on its own"
    return "quiet day, nothing reached a human"


CAPTIONS = {"users": users_caption, "forecast": forecast_caption, "trust": trust_caption, "day": day_caption}


# -------------------------------------------------------------- reason line ---

def human_reason(b: Bundle, result: dict) -> str:
    trigger, detail, states = result["trigger"], result["detail"], result["states"]

    if trigger == "trust_blind":
        return trust_caption(b, "blind", detail["trust"]) + ", the fleet is not visible"

    if trigger in ("users_broken", "critical_incident"):
        opened = open_incidents(b)
        if trigger == "users_broken":
            service = detail["users"].get("service") or "a service"
            head = f"{service} is down"
        else:
            service = opened[0].service if opened else "a service"
            head = f"{service}: critical incident open"
        callers = b.service(service).called_by
        return head + (f", {plural(len(callers), 'more service')} will be hit" if callers else "")

    if trigger == "forecast_imminent":
        info = detail["forecast"]
        match = info["match"]
        return (f"{info['service']}: agent sees {match['matched']} of {match['total']} steps to a failure, "
                f"usually ~{info['leadMin']} min of warning")

    if trigger in ("users_escalated", "users_degraded"):
        info = detail["users"]
        where = join_names(info["affected"] or info["tier1Hurt"])
        return f"{info['failingShare']}% of requests failing" + (f" in {where}" if where else "")

    if trigger == "forecast_risk":
        return forecast_caption(b, "brewing", detail["forecast"])

    if trigger == "day_regressed":
        names = detail["users"].get("affected", [])
        tail = f" in {join_names(names)}" if names and detail["day"].get("because") == "errors" else ""
        return day_caption(b, "regressed", detail["day"]) + tail

    if trigger == "warning_incident":
        opened = open_incidents(b)
        return f"{opened[0].service}: {opened[0].title}" if opened else "a warning incident is open"

    if trigger == "trust_partial":
        caption = trust_caption(b, "partial", detail["trust"])
        return caption + (": healthy or dead, unknown" if "dark_services" in detail["trust"]["reasons"] else "")

    if trigger == "calm_unverified":
        missing = next(k for k in ("day", "forecast", "users") if states[k] == "unknown")
        if missing == "day" and detail["day"].get("why") == "short_history":
            return f"all normal so far; only {detail['day']['historyHours']:g} h of history, the day cannot be judged yet"
        return f"all normal so far; {CAPTIONS[missing](b, 'unknown', detail[missing])}"

    # calm: say the most useful quiet-day thing we know
    if detail["forecast"].get("downgraded"):
        return f"all normal; agent suspects {detail['forecast']['match']['service']} but is wrong more often than right"
    if states["day"] == "settled":
        return day_caption(b, "settled", detail["day"])
    noisy = noisy_log_source(b)
    if noisy:
        return f"{noisy} is noisy in logs, users are not affected"
    return "all normal, nothing happened in the last day"


# --------------------------------------------------------------------- rings ---

def ring_value(key: str, state: str, info: dict) -> float:
    if state == "unknown":
        return 0.0
    if key == "users":
        return clamp(1 - info.get("failingShare", 0) / T.USERS_BROKEN_SHARE_PCT, 0.06)
    if key == "forecast":
        return 0.35 if info.get("pressure") or info.get("stalled") else clamp(1 - info.get("precursorLevel", 0), 0.06)
    if key == "trust":
        if state == "blind":
            return 0.06
        return clamp((info.get("coverage") or 0) / 100 * info.get("freshShare", 0) / 100, 0.06)
    ratio = info.get("ratio") or 1
    return clamp(1 - (ratio - 1) / 2, 0.06)


# ------------------------------------------------------------------ drill-in ---

def fact(label: str, value, hint: str | None = None) -> dict:
    return {"label": label, "value": str(value), **({"hint": hint} if hint else {})}


def users_drill(b: Bundle, info: dict) -> dict:
    rows = []
    for s in b.services.values():
        if not s.rate:
            continue
        down = s.ready is False
        if s.rate.err_pct >= T.SERVICE_BROKEN_ERR_PCT or down:
            flag = "bad"
        else:
            flag = "warn" if s.rate.err_pct >= T.SERVICE_AFFECTED_ERR_PCT else "good"
        rows.append({"service": s.name, "tier": s.tier, "errPct": s.rate.err_pct, "reqPerSec": s.rate.rps, "p99Ms": s.rate.p99_ms,
                     "ready": not down, "fresh": s.rate.age_s is not None and s.rate.age_s <= T.FRESH_S,
                     "hitsNext": list(s.called_by), "flag": flag})
    rows.sort(key=lambda r: (-r["errPct"], -r["reqPerSec"]))
    return {
        "facts": [fact("Requests failing fleet-wide", shown(info.get("failingShare"), "%"), "weighted by traffic"),
                  fact("Services with errors above 1%", len(info.get("affected", []))),
                  fact("Threshold", f"{T.USERS_DEGRADED_SHARE_PCT:g}% schedule, {T.USERS_BROKEN_SHARE_PCT:g}% act now")],
        "services": rows[:8],
    }


def forecast_drill(b: Bundle, info: dict) -> dict:
    match = info.get("match")
    facts = []
    if match:
        facts.append(fact("Pattern", match.get("pattern") or DASH, f"confidence {match['confidence']:.2f}"))
    if info.get("hits", 0) + info.get("misses", 0):
        record = f"{info['hits']} right, {info['misses']} wrong"
        facts.append(fact("Agent track record", record, f"{shown(info.get('precision'), '%')} precision"))
    if info.get("leadMin"):
        facts.append(fact("Usual warning time", f"~{info['leadMin']} min"))
    out: dict = {"facts": facts}
    if match and (match["matchedSteps"] or match["remainingSteps"]):
        out["steps"] = ([{"text": s, "done": True} for s in match["matchedSteps"]]
                        + [{"text": s, "done": False} for s in match["remainingSteps"]])
    if info.get("downgraded"):
        out["note"] = f"Shown dimmed: below {T.FORECAST_MIN_PRECISION_PCT}% precision a forecast cannot move the verdict."
    elif match and info.get("unproven") and info.get("service") == match["service"]:
        out["note"] = (f"Fewer than {T.FORECAST_MIN_SAMPLES} past predictions: this forecast can ask for a ticket, "
                       "not for a person right now.")
    pressure = []
    for name in info.get("pressure", []) + info.get("stalled", []) + info.get("watch", []):
        sat = b.service(name).saturation
        pressure.append({"service": name, "memStallPct": sat.mem_stall_pct, "cpuStallPct": sat.cpu_stall_pct,
                         "ioStallPct": sat.io_stall_pct, "memOfRequestPct": sat.mem_of_request_pct, "oomKills": int(sat.oom_kills or 0)})
    if pressure:
        out["pressure"] = pressure
    return out


def trust_drill(b: Bundle, info: dict) -> dict:
    link = {True: "connected", False: "disconnected", None: "not reported"}[b.agent_connected]
    reporting = (b.services_total or 0) - (b.dark_count or 0)
    facts = [
        fact("Cluster agent", link, f"last message {age_text(b.agent_silent_s)} ago" if b.agent_silent_s is not None else None),
        fact("Services reporting", f"{reporting} of {shown(b.services_total)}", f"{shown(b.coverage_pct, '%')} coverage"),
        fact("Oldest data on screen", age_text(oldest_data_age(b)), f"fresh means under {T.FRESH_S // 60} min"),
        fact("Not in the service graph", b.unmapped),
    ]
    if b.events:
        facts.append(fact("Filtered as noise by the agent", f"{int(b.events.get('noise', 0)):,}",
                          f"{int(b.events.get('signal', 0))} signals, {int(b.events.get('incident', 0))} incidents"))
    out = {"facts": facts, "dark": [{"name": d.name, "silentFor": age_text(d.silent_s)} for d in b.dark]}
    notes = [TRUST_REASONS[r] for r in info.get("reasons", []) if r in TRUST_REASONS] + b.problems
    if notes:
        out["note"] = " · ".join(n[0].upper() + n[1:] for n in notes)
    return out


def day_drill(b: Bundle, info: dict) -> dict:
    points = []
    for i in range(0, len(b.history), 3):
        chunk = b.history[i:i + 3]
        requests = sum(x.requests for x in chunk)
        points.append(round(100 * sum(x.errors for x in chunk) / requests, 3) if requests else 0)
    facts = [
        fact("Errors, last 2 h", shown(info.get("errRecent"), "%"), f"norm {shown(info.get('errBase'), '%')}"),
        fact("Incidents today", shown(info.get("incidentsToday")), f"usual {shown(info.get('normPerDay'))} a day"),
    ]
    if b.sampled_incidents:
        facts.append(fact("Closed by the agent alone", shown(b.auto_resolved_pct, "%")))
        facts.append(fact("Coming back", shown(b.repeat_rate_pct, "%"), f"above {T.DAY_REPEAT_RATE_PCT}% means schedule root-cause work"))
    names = {"log": "Logs", "red": "Requests", "use": "Resources", "k8s": "Platform"}
    out = {
        "facts": facts,
        "sparkline": points,
        "signals": [{"label": names.get(k, k), "count": int(v)} for k, v in b.signals_by_type.items()],
        "handled": [{"service": i.service, "title": i.title, "at": i.first_seen.strftime("%H:%M") if i.first_seen else DASH, "rca": i.rca}
                    for i in b.incidents if i.resolved_by == "agent"],
    }
    if info.get("why") == "short_history":
        out["note"] = f"The day is judged from {T.DAY_MIN_BUCKETS * 5 // 60} h of history. After a core restart this fills up by itself."
    return out


DRILLS = {"users": users_drill, "forecast": forecast_drill, "trust": trust_drill, "day": day_drill}


# ------------------------------------------------------------------- blocks ---

def indicator_cards(b: Bundle, result: dict) -> list[dict]:
    cards = []
    blind = result["verdict"] == "blind"
    how = T.explain()
    for key, meta in INDICATORS.items():
        state = result["states"][key]
        info = result["detail"].get(key, {})
        label, level = STATE_LABELS[state]
        greyed = blind and key != "trust"
        card = {
            "id": key, **meta, "state": state, "label": label,
            "level": "muted" if info.get("downgraded") else level,
            "ring": ring_value(key, state, info),
            # blind: the other three are not "fine" and not "bad", they are unknown
            "caption": "greyed out until data is back" if greyed else CAPTIONS[key](b, state, info),
            "decides": result["decidedBy"] == key,
            "how": how[key],
        }
        if not greyed:
            card["drill"] = DRILLS[key](b, info)
        cards.append(card)
    return cards


def incident_queue(b: Bundle) -> list[dict]:
    queue = []
    for inc in open_incidents(b):
        callers = list(b.service(inc.service).called_by)
        queue.append({
            "id": inc.id, "service": inc.service, "severity": inc.severity, "title": inc.title,
            "openFor": age_text((b.now - inc.first_seen).total_seconds()) if inc.first_seen else DASH,
            "impact": f"hits next: {join_names(callers)}" if callers else "no downstream callers",
            "rca": inc.rca, "plan": list(inc.plan), "related": list(inc.related),
        })
    return queue


def source_block(b: Bundle, mode: str) -> dict:
    return {
        "mode": mode,
        "label": "Demo data" if mode == "demo" else "Live",
        "tenant": b.tenant,
        "cluster": b.cluster,
        # an unreported link with fresh data flowing still counts as alive
        "connected": b.agent_connected is not False and oldest_data_age(b) is not None,
        "age": age_text(b.agent_silent_s if b.agent_silent_s is not None else oldest_data_age(b)),
        "now": b.now.isoformat(timespec="seconds"),
    }


def build_view(data: dict, result: dict, mode: str = "demo") -> dict:
    b = normalize(data)
    # trust can be blind here only when the visible part of the fleet is already broken (engine: evidence can convict)
    unseen = result["states"]["trust"] in ("partial", "blind")
    dim = "partial" if unseen else "unverified" if result["trigger"] == "calm_unverified" else None
    view = {
        "source": source_block(b, mode),
        "decision": {
            "verdict": result["verdict"], **VERDICTS[result["verdict"]],
            "trigger": result["trigger"],
            "reason": human_reason(b, result),
            "dimmed": dim is not None,
            "dimNote": DIM_NOTES.get(dim),
            "rules": [{"id": rid, "text": text, "leadsTo": leads, "fired": rid == result["trigger"]} for rid, text, leads in RULES],
        },
        "indicators": indicator_cards(b, result),
        "queue": incident_queue(b),
    }
    expected = data.get("expected") if isinstance(data, dict) else None
    if expected:
        view["scenario"] = {"id": data.get("scenario", ""), "title": data.get("title", ""), "story": data.get("story", "")}
        view["validation"] = {
            "passed": result["verdict"] == expected["verdict"] and result["states"] == expected["states"],
            "expected": {"verdict": expected["verdict"], "states": expected["states"], "reason": expected.get("reason")},
            "computed": {"verdict": result["verdict"], "states": result["states"]},
        }
    return view
