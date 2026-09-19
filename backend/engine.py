"""The five indicators of metrics_spec.md. This is the only place that decides.

Input is a Bundle (bundle.py), so nothing here touches raw JSON and nothing
here can fail on a missing field: absent data is None, and each indicator says
what None means for it. Numbers come from thresholds.py. Each indicator returns
`(state, info)`; `info` carries every fact presentation.py needs, so the
wording layer never re-derives a decision from raw data.
"""
from __future__ import annotations

import statistics

from backend import thresholds as T
from backend.bundle import Bundle, Precursor, normalize

UNKNOWN = "unknown"

# Which tile gets the "drives the verdict" mark for each rule.
DECIDED_BY = {
    "trust_blind": "trust", "trust_partial": "trust",
    "users_broken": "users", "users_escalated": "users", "users_degraded": "users",
    "forecast_imminent": "forecast", "forecast_risk": "forecast",
    "day_regressed": "day",
    "critical_incident": None, "warning_incident": None, "calm": None, "calm_unverified": None,
}


def _fresh(age_s: float | None) -> bool:
    return age_s is not None and age_s <= T.FRESH_S


# ------------------------------------------------------ 4. Can we trust it ---

def trust(b: Bundle) -> tuple[str, dict]:
    rated = [s for s in b.services.values() if s.rate]
    total_rps = sum(s.rate.rps for s in rated)
    fresh_rps = sum(s.rate.rps for s in rated if _fresh(s.rate.age_s))
    fresh_share = 100 * fresh_rps / total_rps if total_rps else 0.0

    measured = [s for s in b.services.values() if s.saturation]
    fresh_resources = 100 * sum(_fresh(s.saturation.age_s) for s in measured) / len(measured) if measured else 0.0

    info = {
        "coverage": b.coverage_pct, "dark": b.dark_count or 0, "unmapped": b.unmapped,
        "freshShare": round(fresh_share, 1), "freshResourcesShare": round(fresh_resources, 1),
        "agentConnected": b.agent_connected, "reasons": [],
    }

    def blind(reason: str, **extra) -> tuple[str, dict]:
        return "blind", {**info, "reasons": [reason], **extra}

    if not b.tenant_present:
        return blind("tenant_missing")
    if b.agent_connected is False:
        minutes = int(b.agent_silent_s / 60) if b.agent_silent_s is not None else None
        return blind("agent_disconnected", disconnectedMinutes=minutes)
    if not b.services_total:
        return blind("no_services")
    if b.coverage_pct is None:
        return blind("coverage_unknown")
    # The core did not say whether the agent is connected: fresh data is the only evidence left.
    if b.agent_connected is None and fresh_rps == 0:
        return blind("no_fresh_data")
    if b.coverage_pct < T.TRUST_BLIND_COVERAGE_PCT or info["dark"] >= T.TRUST_BLIND_DARK_SERVICES:
        return blind("low_coverage")

    reasons = info["reasons"]
    if info["dark"] > 0:
        reasons.append("dark_services")
    elif b.coverage_pct < T.TRUST_FULL_COVERAGE_PCT:
        reasons.append("low_coverage")
    if b.unmapped > 0:
        reasons.append("unmapped_services")
    if fresh_share < T.TRUST_FRESH_SHARE_PCT:
        reasons.append("stale_traffic")
    # Without fresh resource data the forecast is blind, and that is a collection problem a human can fix.
    if fresh_resources < T.TRUST_FRESH_SHARE_PCT:
        reasons.append("stale_resources" if measured else "no_resource_data")

    return ("partial" if reasons else "full"), info


# ------------------------------------------------------------ 2. Users now ---

def users(b: Bundle) -> tuple[str, dict]:
    failing = traffic = 0.0
    affected: list[str] = []
    tier1_broken: list[str] = []
    tier1_hurt: list[str] = []

    for s in b.services.values():
        on_user_path = s.tier == T.USER_PATH_TIER
        # readiness does not depend on traffic data: a user-path service that is not ready is broken
        if on_user_path and s.ready is False:
            tier1_broken.append(s.name)
        if not s.rate or not _fresh(s.rate.age_s):
            continue
        failing += s.rate.rps * s.rate.err_pct / 100
        traffic += s.rate.rps
        if s.rate.err_pct >= T.SERVICE_AFFECTED_ERR_PCT:
            affected.append(s.name)
        if on_user_path and s.rate.err_pct >= T.SERVICE_BROKEN_ERR_PCT and s.name not in tier1_broken:
            tier1_broken.append(s.name)
        elif on_user_path and s.rate.err_pct >= T.SERVICE_AFFECTED_ERR_PCT and s.name not in tier1_broken:
            tier1_hurt.append(s.name)

    if traffic == 0 and not tier1_broken:
        return UNKNOWN, {"why": "no fresh traffic data", "affected": []}

    share = 100 * failing / traffic if traffic else 0.0
    # max, not sum: blastRadius values of neighbouring services overlap
    blast_max = max((b.service(n).blast_radius or 0.0 for n in affected), default=0.0)
    info = {"failingShare": round(share, 2), "affected": affected, "blastMax": round(blast_max, 2),
            "tier1Broken": tier1_broken, "tier1Hurt": tier1_hurt}

    if share >= T.USERS_BROKEN_SHARE_PCT or tier1_broken:
        info["service"] = (tier1_broken or affected or [None])[0]
        return "broken", info
    if share >= T.USERS_DEGRADED_SHARE_PCT or tier1_hurt:
        info["escalate"] = blast_max >= T.ESCALATE_BLAST_RADIUS
        return "degraded", info
    return "ok", info


# -------------------------------------------------------- 3. What's brewing ---

def _weighted(p: Precursor) -> float:
    return p.confidence if p.progress >= T.PRECURSOR_MIN_PROGRESS else p.confidence * 0.5


def forecast(b: Bundle) -> tuple[str, dict]:
    sampled = b.prediction_hits + b.prediction_misses
    info: dict = {
        "precision": b.prediction_precision_pct, "hits": b.prediction_hits, "misses": b.prediction_misses,
        "leadMin": round(b.prediction_lead_ms / 60000) if b.prediction_lead_ms else None,
        "pressure": [], "watch": [], "match": None, "service": None, "downgraded": False, "actNow": False,
    }

    best = max(b.precursors, key=_weighted, default=None)
    level = _weighted(best) if best else 0.0
    info["precursorLevel"] = round(level, 2)
    if best:
        info["match"] = {"service": best.service, "pattern": best.pattern, "confidence": best.confidence,
                         "matched": best.matched, "total": best.total,
                         "matchedSteps": list(best.matched_steps), "remainingSteps": list(best.remaining_steps)}

    measured = [s for s in b.services.values() if s.saturation and _fresh(s.saturation.age_s)]
    for s in measured:
        sat = s.saturation
        saturating = ((sat.mem_stall_pct or 0) >= T.PRESSURE_STALL_PCT
                      and (sat.mem_of_request_pct or 0) >= T.PRESSURE_MEM_OF_REQUEST_PCT)
        if saturating or (sat.oom_kills or 0) > 0:
            info["pressure"].append(s.name)
        elif sat.worst_stall_pct >= T.PRESSURE_STALL_PCT:
            info["watch"].append(s.name)
    info["oomStarted"] = any((b.service(n).saturation.oom_kills or 0) > 0 for n in info["pressure"])

    # No fresh resource data and no pattern match: "nothing is brewing" would be a guess.
    if not measured and not best:
        return UNKNOWN, {**info, "why": "no fresh resource data"}

    if info["pressure"]:
        state, info["service"] = "brewing", info["pressure"][0]
    elif level >= T.PRECURSOR_BREWING_CONFIDENCE:
        state, info["service"] = "brewing", best.service
        unreliable = (sampled >= T.FORECAST_MIN_SAMPLES and b.prediction_precision_pct is not None
                      and b.prediction_precision_pct < T.FORECAST_MIN_PRECISION_PCT)
        if unreliable:
            state, info["downgraded"] = "pressure", True
    elif level >= T.PRECURSOR_PRESSURE_CONFIDENCE:
        state, info["service"] = "pressure", best.service
    elif info["watch"]:
        state, info["service"] = "pressure", info["watch"][0]
    else:
        state = "clear"

    info["actNow"] = bool(
        state == "brewing" and not info["downgraded"]
        and b.service(info["service"]).tier == T.USER_PATH_TIER
        and b.prediction_lead_ms is not None and b.prediction_lead_ms < T.ACT_NOW_LEAD_MS
    )
    return state, info


# ------------------------------------------------------ 5. How the day went ---

def day(b: Bundle) -> tuple[str, dict]:
    history = b.history
    info: dict = {"historyHours": round(len(history) * 5 / 60, 1), "openNow": b.open_now}
    if len(history) < T.DAY_MIN_BUCKETS:
        return UNKNOWN, {**info, "why": "short_history"}

    recent, base = history[-T.DAY_RECENT_BUCKETS:], history[:-T.DAY_RECENT_BUCKETS]
    recent_requests, base_requests = sum(x.requests for x in recent), sum(x.requests for x in base)
    if recent_requests == 0 or base_requests < T.DAY_MIN_BASE_REQUESTS:
        return UNKNOWN, {**info, "why": "low_traffic"}

    err_recent = 100 * sum(x.errors for x in recent) / recent_requests
    err_base = 100 * sum(x.errors for x in base) / base_requests
    elevated = T.DAY_ELEVATED_RATIO * err_base

    # a spike is named by when it started, not by its tallest bucket
    peak_index = max(range(len(history)), key=lambda i: history[i].err_pct)
    peak = history[peak_index].err_pct
    while peak_index > 0 and history[peak_index - 1].err_pct > elevated:
        peak_index -= 1
    since = None
    for bucket in reversed(history):
        if bucket.err_pct <= elevated:
            break
        since = bucket

    start_of_day = b.now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = sum(1 for i in b.incidents if i.first_seen and i.first_seen >= start_of_day)
    per_day = statistics.median(b.weekly_incident_counts) / 7 if b.weekly_incident_counts else None
    repeat = b.repeat_rate_pct or 0.0

    def clock(bucket) -> str | None:
        return bucket.t.strftime("%H:%M") if bucket and bucket.t else None

    info.update({
        "errRecent": round(err_recent, 2), "errBase": round(err_base, 2), "peakBucket": round(peak, 2),
        "ratio": round(err_recent / err_base, 2) if err_base else None,
        "spikeAt": clock(history[peak_index]), "since": clock(since),
        "incidentsToday": today, "normPerDay": round(per_day, 2) if per_day is not None else None, "repeatRate": repeat,
    })

    errors_up = err_recent > T.DAY_REGRESSED_RATIO * err_base and err_recent >= T.DAY_REGRESSED_FLOOR_PCT
    # without a baseline of usual incidents, a count cannot be called unusual
    incidents_up = per_day is not None and today > T.DAY_INCIDENT_RATIO * per_day
    if errors_up or repeat > T.DAY_REPEAT_RATE_PCT or incidents_up:
        info["because"] = "errors" if errors_up else "repeats" if repeat > T.DAY_REPEAT_RATE_PCT else "incidents"
        return "regressed", info
    if peak > T.DAY_SPIKE_RATIO * err_base and err_recent <= T.DAY_SETTLED_RATIO * err_base and b.open_now == 0:
        return "settled", info
    return "quiet", info


# ----------------------------------------------------------- 1. Fleet state ---

def evaluate(b: Bundle) -> dict:
    trust_state, trust_info = trust(b)
    if trust_state == "blind":
        return {"verdict": "blind", "trigger": "trust_blind", "decidedBy": "trust",
                "states": {"users": UNKNOWN, "forecast": UNKNOWN, "trust": trust_state, "day": UNKNOWN},
                "detail": {"trust": trust_info}, "problems": b.problems}

    users_state, users_info = users(b)
    forecast_state, forecast_info = forecast(b)
    day_state, day_info = day(b)

    if users_state == "broken":
        verdict_, trigger = "act_now", "users_broken"
    elif b.critical_open > 0:
        verdict_, trigger = "act_now", "critical_incident"
    elif forecast_state == "brewing" and forecast_info["actNow"]:
        verdict_, trigger = "act_now", "forecast_imminent"
    elif users_state == "degraded" and users_info.get("escalate"):
        verdict_, trigger = "act_now", "users_escalated"
    elif users_state == "degraded":
        verdict_, trigger = "schedule", "users_degraded"
    elif forecast_state == "brewing":
        verdict_, trigger = "schedule", "forecast_risk"
    elif day_state == "regressed":
        verdict_, trigger = "schedule", "day_regressed"
    elif b.warning_open > 0:
        verdict_, trigger = "schedule", "warning_incident"
    elif trust_state == "partial":
        verdict_, trigger = "schedule", "trust_partial"
    elif UNKNOWN in (users_state, forecast_state, day_state):
        # Nothing calls for work, but one vital could not be judged. Short history heals by itself, so
        # there is nothing to schedule: the word stays ALL CLEAR, dimmed, and the reason says what is missing.
        verdict_, trigger = "all_clear", "calm_unverified"
    else:
        verdict_, trigger = "all_clear", "calm"

    return {
        "verdict": verdict_, "trigger": trigger, "decidedBy": DECIDED_BY[trigger],
        "states": {"users": users_state, "forecast": forecast_state, "trust": trust_state, "day": day_state},
        "detail": {"users": users_info, "forecast": forecast_info, "trust": trust_info, "day": day_info,
                   "criticalOpen": b.critical_open, "warningOpen": b.warning_open},
        "problems": b.problems,
    }


def verdict(data: dict | Bundle) -> dict:
    """Decide from a raw scenario or live bundle. Never raises on missing fields."""
    return evaluate(data if isinstance(data, Bundle) else normalize(data))
