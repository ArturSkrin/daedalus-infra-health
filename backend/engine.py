from __future__ import annotations

import statistics
from datetime import datetime


FRESH_S = 300
DAY_FLOOR_PCT = 0.3
MIN_BUCKETS = 230
RECENT_BUCKETS = 24


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# Indicator 4: Trust
# ---------------------------------------------------------------------------

def trust(data: dict) -> tuple[str, dict]:
    now = parse(data["now"]).timestamp()

    tenant = (
        data["status"]
        .get("tenantStats", {})
        .get("tenants", {})
        .get(data["tenant"])
    )

    agent = (
        data["status"]
        .get("clusterAgentStats", {})
        .get(data["tenant"], {})
    )

    if tenant is None:
        return "Наосліп", {
            "why": "tenant missing",
        }

    if not agent.get("connected", False):
        last_message = agent.get("lastMessageUnix", now)
        minutes = int((now - last_message) / 60)

        return "Наосліп", {
            "why": f"agent disconnected {minutes} min",
            "disconnectedMinutes": minutes,
        }

    if tenant.get("services", 0) == 0:
        return "Наосліп", {
            "why": "services = 0",
        }

    coverage = tenant.get("serviceCoveragePct", 0)
    dark = tenant.get("servicesDark", 0)
    unmapped = data["status"].get("unmappedServices", 0)

    total_rps = 0.0
    fresh_rps = 0.0

    for app in data["applications"]:
        golden = app.get("golden", {})

        if "reqPerSec" not in golden:
            continue

        rps = golden["reqPerSec"]
        total_rps += rps

        if now - golden.get("rateAsOfUnix", 0) <= FRESH_S:
            fresh_rps += rps

    fresh_share = (
        100 * fresh_rps / total_rps
        if total_rps
        else 0
    )

    info = {
        "coverage": coverage,
        "dark": dark,
        "unmapped": unmapped,
        "freshShare": round(fresh_share, 1),
    }

    if coverage < 80 or dark >= 3:
        return "Наосліп", info

    if (
        coverage < 95
        or 1 <= dark <= 2
        or unmapped > 0
        or fresh_share < 90
    ):
        return "Частково", info

    return "Повна", info


# ---------------------------------------------------------------------------
# Indicator 2: Users now
# ---------------------------------------------------------------------------

def users(data: dict) -> tuple[str, dict]:
    now = parse(data["now"]).timestamp()

    nodes = {
        node["name"]: node
        for node in data["graph"]["nodes"]
    }

    numerator = 0.0
    denominator = 0.0

    affected: list[str] = []
    tier1_broken: list[str] = []
    tier1_hurt: list[str] = []

    for app in data["applications"]:
        golden = app.get("golden", {})

        if "reqPerSec" not in golden:
            continue

        if now - golden.get("rateAsOfUnix", 0) > FRESH_S:
            continue

        rps = golden["reqPerSec"]
        error_pct = golden["errPct"]

        numerator += rps * error_pct / 100
        denominator += rps

        node = nodes.get(
            app["name"],
            {
                "tier": 3,
                "blastRadius": 0,
            },
        )

        if error_pct >= 1:
            affected.append(app["name"])

        if (
            node["tier"] == 1
            and (
                error_pct >= 5
                or not app.get("ready", True)
            )
        ):
            tier1_broken.append(app["name"])

        elif (
            node["tier"] == 1
            and error_pct >= 1
        ):
            tier1_hurt.append(app["name"])

    if denominator == 0:
        return "—", {
            "why": "no fresh rate data",
        }

    failing_share = 100 * numerator / denominator

    blast_max = max(
        (
            nodes[service]["blastRadius"]
            for service in affected
            if service in nodes
        ),
        default=0,
    )

    info = {
        "failingShare": round(failing_share, 2),
        "affected": affected,
        "blastMax": round(blast_max, 2),
    }

    if failing_share >= 5 or tier1_broken:
        info["tier1Broken"] = tier1_broken

        return "Зламано", info

    if failing_share >= 0.5 or tier1_hurt:
        info["tier1Hurt"] = tier1_hurt
        info["escalate"] = blast_max >= 0.5

        return "Страждають", info

    return "Добре", info


# ---------------------------------------------------------------------------
# Indicator 3: Forecast
# ---------------------------------------------------------------------------

def forecast(data: dict) -> tuple[str, dict]:
    now = parse(data["now"]).timestamp()

    tenant = (
        data["status"]["tenantStats"]["tenants"][data["tenant"]]
    )

    nodes = {
        node["name"]: node
        for node in data["graph"]["nodes"]
    }

    hits = tenant.get("predictionHits", 0)
    misses = tenant.get("predictionMisses", 0)
    precision = tenant.get("predictionPrecisionPct")

    lead_ms = (
        tenant.get("predictionAvgLeadMs")
        if hits
        else None
    )

    info = {
        "precision": precision,
        "leadMin": (
            round(lead_ms / 60000)
            if lead_ms
            else None
        ),
    }

    level = "Чисто"
    service = None
    best = 0.0

    for match in data["analytics"].get(
        "precursorMatches",
        [],
    ):
        ratio = (
            match["matchedSteps"]
            / match["totalSteps"]
        )

        confidence = (
            match["confidence"]
            if ratio >= 0.5
            else match["confidence"] * 0.5
        )

        if confidence > best:
            best = confidence
            service = match["service"]

    if best >= 0.7:
        level = "Назріває"

    elif best >= 0.5:
        level = "Тисне"

    info["precursorLevel"] = round(best, 2)

    pressure: list[str] = []

    for app in data["applications"]:
        golden = app.get("golden", {})

        if (
            now
            - golden.get("saturationAsOfUnix", 0)
            > FRESH_S
        ):
            continue

        if (
            (
                golden.get("memPsiPct", 0) >= 1
                and golden.get("memReqPct", 0) >= 90
            )
            or golden.get("oomKills", 0) > 0
        ):
            pressure.append(app["name"])

        elif (
            max(
                golden.get("memPsiPct", 0),
                golden.get("cpuPsiPct", 0),
                golden.get("ioPsiPct", 0),
            )
            >= 1
            and level == "Чисто"
        ):
            level = "Тисне"

    if pressure:
        level = "Назріває"
        service = service or pressure[0]

    info["pressure"] = pressure

    if (
        level == "Назріває"
        and best >= 0.7
        and not pressure
        and hits + misses >= 10
        and precision is not None
        and precision < 60
    ):
        level = "Тисне"
        info["downgraded"] = True

    info["service"] = service

    tier1 = (
        service in nodes
        and nodes[service]["tier"] == 1
    )

    info["actNow"] = bool(
        level == "Назріває"
        and tier1
        and lead_ms is not None
        and lead_ms < 30 * 60000
        and not info.get("downgraded")
    )

    return level, info


# ---------------------------------------------------------------------------
# Indicator 5: Day
# ---------------------------------------------------------------------------

def day(data: dict) -> tuple[str, dict]:
    tenant = (
        data["status"]["tenantStats"]["tenants"][data["tenant"]]
    )

    history = tenant.get(
        "signalsHistory",
        [],
    )

    if len(history) < MIN_BUCKETS:
        return "—", {
            "why": f"only {len(history)} buckets",
        }

    recent = history[-RECENT_BUCKETS:]
    base = history[:-RECENT_BUCKETS]

    recent_requests = sum(
        bucket["requests"]
        for bucket in recent
    )

    recent_errors = sum(
        bucket["requestErrors"]
        for bucket in recent
    )

    base_requests = sum(
        bucket["requests"]
        for bucket in base
    )

    base_errors = sum(
        bucket["requestErrors"]
        for bucket in base
    )

    if recent_requests == 0:
        return "—", {
            "why": "recent window has no requests",
        }

    if base_requests < 1000:
        return "—", {
            "why": "base window too small",
        }

    err_recent = (
        100 * recent_errors / recent_requests
    )

    err_base = (
        100 * base_errors / base_requests
    )

    peak = max(
        (
            100
            * bucket["requestErrors"]
            / bucket["requests"]
            for bucket in history
            if bucket["requests"]
        ),
        default=0,
    )

    now = parse(data["now"])

    start_of_day = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    incidents_today = sum(
        1
        for incident
        in data["incidents"]["incidents"]
        if parse(incident["firstSeen"])
        >= start_of_day
    )

    weeks: dict[str, int] = {}

    for baseline in data["analytics"]["baselines"]:
        for week, count in baseline.get(
            "weeklyIncidentCounts",
            {},
        ).items():
            weeks[week] = (
                weeks.get(week, 0)
                + count
            )

    weekly_median = (
        statistics.median(weeks.values())
        if weeks
        else 0
    )

    norm_per_day = weekly_median / 7

    repeat_rate = (
        tenant.get("repeatRatePct", 0)
        if tenant.get("sampledIncidents")
        else 0
    )

    info = {
        "errRecent": round(err_recent, 2),
        "errBase": round(err_base, 2),
        "peakBucket": round(peak, 2),
        "incidentsToday": incidents_today,
        "normPerDay": round(norm_per_day, 2),
        "repeatRate": repeat_rate,
    }

    if (
        (
            err_recent > 2 * err_base
            and err_recent >= DAY_FLOOR_PCT
        )
        or repeat_rate > 20
        or incidents_today > 2 * norm_per_day
    ):
        return "Погіршилась", info

    open_now = (
        tenant
        .get("incidents", {})
        .get("openNow", 0)
    )

    if (
        peak > 3 * err_base
        and err_recent <= 1.5 * err_base
        and open_now == 0
    ):
        return "Осіла", info

    return "Спокійна", info


# ---------------------------------------------------------------------------
# Indicator 1: Final decision
# ---------------------------------------------------------------------------

def verdict(data: dict) -> dict:
    trust_state, trust_info = trust(data)

    if trust_state == "Наосліп":
        return {
            "verdict": "НАОСЛІП",
            "trigger": "trust_blind",
            "states": {
                "users": "—",
                "forecast": "—",
                "trust": trust_state,
                "day": "—",
            },
            "detail": {
                "trust": trust_info,
            },
        }

    users_state, users_info = users(data)
    forecast_state, forecast_info = forecast(data)
    day_state, day_info = day(data)

    critical_open = (
        data["incidents"]["incidentMetrics"]
        .get("criticalOpen", 0)
    )

    warning_open = (
        data["incidents"]["incidentMetrics"]
        .get("warningOpen", 0)
    )

    if users_state == "Зламано":
        final_verdict = "ЗАРАЗ"
        trigger = "users_broken"

    elif critical_open > 0:
        final_verdict = "ЗАРАЗ"
        trigger = "critical_incident"

    elif (
        forecast_state == "Назріває"
        and forecast_info.get("actNow")
    ):
        final_verdict = "ЗАРАЗ"
        trigger = "forecast_imminent"

    elif (
        users_state == "Страждають"
        and users_info.get("escalate")
    ):
        final_verdict = "ЗАРАЗ"
        trigger = "users_escalated"

    elif users_state == "Страждають":
        final_verdict = "ЗАПЛАНУВАТИ"
        trigger = "users_degraded"

    elif forecast_state == "Назріває":
        final_verdict = "ЗАПЛАНУВАТИ"
        trigger = "forecast_risk"

    elif day_state == "Погіршилась":
        final_verdict = "ЗАПЛАНУВАТИ"
        trigger = "day_regressed"

    elif warning_open > 0:
        final_verdict = "ЗАПЛАНУВАТИ"
        trigger = "warning_incident"

    elif trust_state == "Частково":
        final_verdict = "ЗАПЛАНУВАТИ"
        trigger = "trust_partial"

    else:
        final_verdict = "СПОКІЙНО"
        trigger = "calm"

    return {
        "verdict": final_verdict,
        "trigger": trigger,
        "states": {
            "users": users_state,
            "forecast": forecast_state,
            "trust": trust_state,
            "day": day_state,
        },
        "detail": {
            "users": users_info,
            "forecast": forecast_info,
            "trust": trust_info,
            "day": day_info,
            "criticalOpen": critical_open,
            "warningOpen": warning_open,
        },
    }
