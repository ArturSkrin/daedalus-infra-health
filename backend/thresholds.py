"""Every threshold of the five indicators, in one place.

Names follow metrics_spec.md. engine.py reads the numbers, and `explain()`
turns the same numbers into the "How this indicator decides" text the screen
shows, so a threshold is never written down twice.
"""
from __future__ import annotations

# --- shared ---------------------------------------------------------------
FRESH_S = 300                      # a golden block older than this is excluded, not read as zero
USER_PATH_TIER = 1                 # tier of services on the user path

# --- 2. Users now ---------------------------------------------------------
USERS_DEGRADED_SHARE_PCT = 0.5     # fleet-wide failing share: Fine below, Degraded from
USERS_BROKEN_SHARE_PCT = 5.0       # fleet-wide failing share: Broken from
SERVICE_AFFECTED_ERR_PCT = 1.0     # a service counts as affected from
SERVICE_BROKEN_ERR_PCT = 5.0       # a user-path service counts as broken from
ESCALATE_BLAST_RADIUS = 0.5        # Degraded becomes ACT NOW when the worst affected service reaches this

# --- 3. What's brewing ----------------------------------------------------
PRECURSOR_BREWING_CONFIDENCE = 0.7
PRECURSOR_PRESSURE_CONFIDENCE = 0.5
PRECURSOR_MIN_PROGRESS = 0.5       # matchedSteps / totalSteps; below it confidence is halved
PRESSURE_STALL_PCT = 1.0           # PSI, any resource
PRESSURE_MEM_OF_REQUEST_PCT = 90   # memory stall only counts as saturating above this share of the request
PRESSURE_SEVERE_STALL_PCT = 10.0   # any resource stalled this much is brewing on its own, memory or not
FORECAST_MIN_PRECISION_PCT = 60    # below it a forecast is dimmed and cannot move the verdict
FORECAST_MIN_SAMPLES = 10          # hits + misses needed before precision is believed, and before a forecast may say ACT NOW
ACT_NOW_LEAD_MS = 30 * 60 * 1000   # user-path service with less warning than this: ACT NOW

# --- 4. Can we trust it ---------------------------------------------------
TRUST_FULL_COVERAGE_PCT = 95
TRUST_BLIND_COVERAGE_PCT = 80
TRUST_BLIND_DARK_SERVICES = 3
TRUST_FRESH_SHARE_PCT = 90         # share of traffic (rate) or of services (resources) with fresh data
TRUST_UNCLASSIFIED_SHARE_PCT = 20  # events the agent could not classify; above this its triage is not the full picture

# --- 5. How the day went --------------------------------------------------
DAY_RECENT_BUCKETS = 24            # last 2 h of 5-minute buckets, compared with the rest
DAY_MIN_BUCKETS = 230              # 80 % of 24 h, below it the day cannot be judged
DAY_MIN_BASE_REQUESTS = 1000
DAY_REGRESSED_RATIO = 2.0          # recent error share vs the norm
DAY_REGRESSED_FLOOR_PCT = 0.3      # and at least this much in absolute terms
DAY_SPIKE_RATIO = 3.0              # a bucket this far above the norm is a spike
DAY_SETTLED_RATIO = 1.5            # recent share back under this: the spike settled
DAY_ELEVATED_RATIO = 1.5           # a bucket above this belongs to an elevated run
DAY_REPEAT_RATE_PCT = 20
DAY_INCIDENT_RATIO = 2.0           # incidents today vs the usual per day


def _n(value: float) -> str:
    """0.5 -> '0.5', 5.0 -> '5'."""
    return f"{value:g}"


def explain() -> dict[str, str]:
    """Human wording of the rules, built from the numbers above."""
    return {
        "users": (
            f"Fine while under {_n(USERS_DEGRADED_SHARE_PCT)}% of requests fail. Degraded from {_n(USERS_DEGRADED_SHARE_PCT)}%, "
            f"or when a service on the user path passes {_n(SERVICE_AFFECTED_ERR_PCT)}%: schedule, and act now if that service "
            f"is on the user path. Broken from {_n(USERS_BROKEN_SHARE_PCT)}% fleet-wide, or when a user-path service passes "
            f"{_n(SERVICE_BROKEN_ERR_PCT)}% or is not ready: act now."
        ),
        "forecast": (
            f"Brewing when the agent matches at least {_n(PRECURSOR_MIN_PROGRESS * 100)}% of a known failure pattern with "
            f"{_n(PRECURSOR_BREWING_CONFIDENCE * 100)}% confidence, or when memory stalls while usage is above "
            f"{PRESSURE_MEM_OF_REQUEST_PCT}% of its request, or when any resource stalls a service {_n(PRESSURE_SEVERE_STALL_PCT)}% "
            f"of the time: schedule, and act now if it is a user-path service with under {ACT_NOW_LEAD_MS // 60000} min of usual "
            f"warning and the agent has at least {FORECAST_MIN_SAMPLES} past predictions to judge it by. A forecast from an agent "
            f"that is right less than {FORECAST_MIN_PRECISION_PCT}% of the time is dimmed and cannot move the verdict."
        ),
        "trust": (
            f"Full when the cluster agent is connected, {TRUST_FULL_COVERAGE_PCT}% of services report, none are silent, and "
            f"data is under {FRESH_S // 60} min old. Partial, which also covers an agent that could not classify "
            f"{TRUST_UNCLASSIFIED_SHARE_PCT}% of events, blocks ALL CLEAR, because a silent service is either healthy or dead "
            f"and the data cannot tell which. Blind, under {TRUST_BLIND_COVERAGE_PCT}% coverage or with the agent gone, greys "
            f"out everything else."
        ),
        "day": (
            f"Compares errors in the last {DAY_RECENT_BUCKETS * 5 // 60} hours with the {24 - DAY_RECENT_BUCKETS * 5 // 60} hours "
            f"before. Regressed above {_n(DAY_REGRESSED_RATIO)} times the norm: schedule. Settled when there was a spike that came "
            f"back down with nothing left open. Quiet otherwise. This is also where you see what the agent closed without you."
        ),
    }
