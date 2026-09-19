"""Each threshold of metrics_spec.md, checked on both sides of the line."""
from __future__ import annotations

import pytest

from backend import thresholds as T
from backend.engine import verdict
from tests.conftest import app_of, tenant_of


def set_errors(data: dict, pct: float, only: str | None = None):
    for app in data["applications"]:
        if "errPct" in app["golden"] and (only is None or app["name"] == only):
            app["golden"]["errPct"] = pct


def precursor(service="payments", confidence=0.84, matched=4, total=5) -> list[dict]:
    return [{"service": service, "confidence": confidence, "matchedSteps": matched, "totalSteps": total}]


@pytest.mark.parametrize("pct, state", [(0.49, "ok"), (0.5, "degraded")])
def test_fleet_failing_share_boundary(calm, pct, state):
    set_errors(calm, pct)
    assert verdict(calm)["states"]["users"] == state


def test_degraded_off_the_user_path_is_schedule(calm):
    set_errors(calm, 0.1)
    set_errors(calm, 3.0, only="catalog")          # tier 2, blast radius 0.31
    result = verdict(calm)
    assert (result["states"]["users"], result["verdict"], result["trigger"]) == ("degraded", "schedule", "users_degraded")


def test_degraded_on_the_user_path_is_act_now(calm):
    set_errors(calm, 0.1)
    set_errors(calm, 1.0, only="checkout")         # tier 1, blast radius 0.62
    result = verdict(calm)
    assert (result["states"]["users"], result["verdict"], result["trigger"]) == ("degraded", "act_now", "users_escalated")


@pytest.mark.parametrize("pct, state", [(4.9, "degraded"), (5.0, "broken")])
def test_user_path_service_broken_boundary(calm, pct, state):
    set_errors(calm, 0.1)
    set_errors(calm, pct, only="checkout")
    assert verdict(calm)["states"]["users"] == state


def test_user_path_service_not_ready_is_broken_even_with_stale_traffic(calm):
    app_of(calm, "checkout")["ready"] = False
    app_of(calm, "checkout")["golden"]["rateAsOfUnix"] -= 3600
    result = verdict(calm)
    assert result["states"]["users"] == "broken"
    assert result["detail"]["users"]["service"] == "checkout"


def test_stale_traffic_is_excluded_not_read_as_current(calm):
    set_errors(calm, 40.0, only="checkout")
    app_of(calm, "checkout")["golden"]["rateAsOfUnix"] -= T.FRESH_S + 60
    result = verdict(calm)
    assert result["states"]["users"] == "ok"                           # the stale 40 % is not trusted
    assert "stale_traffic" not in result["detail"]["trust"]["reasons"]  # 85 of 1377 rps stale: still above 90 % fresh


@pytest.mark.parametrize("confidence, state", [(0.49, "clear"), (0.5, "pressure"), (0.69, "pressure"), (0.7, "brewing")])
def test_precursor_confidence_boundaries(calm, confidence, state):
    calm["analytics"]["precursorMatches"] = precursor(confidence=confidence)
    assert verdict(calm)["states"]["forecast"] == state


def test_early_pattern_match_counts_for_half(calm):
    calm["analytics"]["precursorMatches"] = precursor(confidence=0.9, matched=2, total=5)   # 0.9 * 0.5 = 0.45
    assert verdict(calm)["states"]["forecast"] == "clear"


def test_engine_and_screen_name_the_same_precursor(calm):
    """Two matches: the engine weighs progress, so the screen must not pick by raw confidence."""
    calm["analytics"]["precursorMatches"] = precursor("auth", 0.95, 1, 5) + precursor("payments", 0.8, 4, 5)
    info = verdict(calm)["detail"]["forecast"]
    assert info["service"] == info["match"]["service"] == "payments"


@pytest.mark.parametrize("lead_min, word", [(29, "act_now"), (30, "schedule")])
def test_warning_time_boundary_on_the_user_path(calm, lead_min, word):
    calm["analytics"]["precursorMatches"] = precursor("payments")
    tenant_of(calm)["predictionAvgLeadMs"] = lead_min * 60_000
    assert verdict(calm)["verdict"] == word


def test_short_warning_off_the_user_path_is_schedule(calm):
    calm["analytics"]["precursorMatches"] = precursor("catalog")
    tenant_of(calm)["predictionAvgLeadMs"] = 5 * 60_000
    assert verdict(calm)["verdict"] == "schedule"


@pytest.mark.parametrize("precision, hits, misses, downgraded", [(59, 5, 5, True), (60, 6, 4, False), (40, 4, 5, False)])
def test_unreliable_agent_cannot_move_the_verdict(calm, precision, hits, misses, downgraded):
    calm["analytics"]["precursorMatches"] = precursor("catalog")
    tenant_of(calm).update(predictionPrecisionPct=precision, predictionHits=hits, predictionMisses=misses)
    result = verdict(calm)
    assert result["detail"]["forecast"]["downgraded"] is downgraded
    assert result["verdict"] == ("all_clear" if downgraded else "schedule")


def test_memory_saturation_needs_both_stall_and_request_share(calm):
    golden = app_of(calm, "catalog")["golden"]
    golden.update(memPsiPct=2.4, memReqPct=89)
    assert verdict(calm)["states"]["forecast"] == "pressure"
    golden.update(memReqPct=90)
    assert verdict(calm)["states"]["forecast"] == "brewing"


def test_oom_kill_alone_is_brewing(calm):
    app_of(calm, "catalog")["golden"]["oomKills"] = 1
    result = verdict(calm)
    assert result["states"]["forecast"] == "brewing"
    assert result["detail"]["forecast"]["oomStarted"] is True


@pytest.mark.parametrize("coverage, dark, state", [(95, 0, "full"), (94, 0, "partial"), (100, 1, "partial"),
                                                   (80, 2, "partial"), (79, 2, "blind"), (100, 3, "blind")])
def test_trust_boundaries(calm, coverage, dark, state):
    tenant_of(calm).update(serviceCoveragePct=coverage, servicesDark=dark)
    assert verdict(calm)["states"]["trust"] == state


def test_partial_trust_forbids_all_clear(calm):
    tenant_of(calm).update(serviceCoveragePct=92, servicesDark=1)
    result = verdict(calm)
    assert (result["verdict"], result["trigger"]) == ("schedule", "trust_partial")


def test_short_history_keeps_all_clear_but_marks_it_unverified(calm):
    tenant_of(calm)["signalsHistory"] = tenant_of(calm)["signalsHistory"][-(T.DAY_MIN_BUCKETS - 1):]
    result = verdict(calm)
    assert result["states"]["day"] == "unknown"
    assert (result["verdict"], result["trigger"]) == ("all_clear", "calm_unverified")


def test_open_incident_blocks_settled(calm):
    history = tenant_of(calm)["signalsHistory"]
    for bucket in history[100:103]:
        bucket["requestErrors"] = int(bucket["requests"] * 0.02)     # a spike, long gone
    assert verdict(calm)["states"]["day"] == "settled"
    tenant_of(calm)["incidents"]["openNow"] = 1
    assert verdict(calm)["states"]["day"] == "quiet"


def test_log_storm_moves_nothing(calm):
    tenant_of(calm)["signalsByType"] = {"log": 250_000, "red": 0, "use": 0, "k8s": 0}
    tenant_of(calm)["events"]["noise"] = 250_000
    assert verdict(calm)["verdict"] == "all_clear"


def test_explanations_quote_the_real_thresholds():
    text = T.explain()
    assert f"{T.USERS_DEGRADED_SHARE_PCT:g}%" in text["users"]
    assert f"{T.FORECAST_MIN_PRECISION_PCT}%" in text["forecast"]
    assert f"{T.TRUST_FULL_COVERAGE_PCT}%" in text["trust"]


# --- found by playing the mentor against our own rules -------------------------

@pytest.mark.parametrize("hits, misses, word", [(1, 0, "schedule"), (9, 0, "schedule"), (10, 0, "act_now")])
def test_agent_without_a_track_record_cannot_say_act_now(calm, hits, misses, word):
    """One lucky prediction is 100 % precision. It may ask for a ticket, not for a person right now."""
    calm["analytics"]["precursorMatches"] = precursor("payments", confidence=0.95)
    tenant_of(calm).update(predictionHits=hits, predictionMisses=misses, predictionPrecisionPct=100, predictionAvgLeadMs=10 * 60_000)
    result = verdict(calm)
    assert result["states"]["forecast"] == "brewing"
    assert result["verdict"] == word


@pytest.mark.parametrize("resource, key", [("CPU", "cpuPsiPct"), ("disk", "ioPsiPct"), ("memory", "memPsiPct")])
@pytest.mark.parametrize("stall, state", [(9.9, "pressure"), (10.0, "brewing")])
def test_severe_stall_of_any_resource_is_brewing(calm, resource, key, stall, state):
    """The agent opens no incident for resource pressure, so a stalled service must not pass as ALL CLEAR."""
    app_of(calm, "catalog")["golden"][key] = stall
    result = verdict(calm)
    assert result["states"]["forecast"] == state
    assert result["verdict"] == ("schedule" if state == "brewing" else "all_clear")
    if state == "brewing":
        assert result["detail"]["forecast"]["stalledResource"] == resource


@pytest.mark.parametrize("unknown, state", [(3_500, "full"), (3_600, "partial")])     # 19.7 % and 20.1 % of events
def test_unclassified_events_are_a_trust_problem(calm, unknown, state):
    tenant_of(calm)["events"] = {"noise": 14_210, "signal": 96, "incident": 0, "unknown": unknown, "drift": 0}
    result = verdict(calm)
    assert result["states"]["trust"] == state
    if state == "partial":
        assert result["detail"]["trust"]["reasons"] == ["unclassified_events"]
        assert result["verdict"] == "schedule"


def test_signal_share_alone_never_moves_the_screen(calm):
    """snrPct has no baseline in the API: 0.7 % is this fleet on a quiet day, so it cannot be thresholded."""
    tenant_of(calm)["snrPct"] = 0.01
    assert verdict(calm)["verdict"] == "all_clear"


def test_settled_spike_does_not_credit_the_agent_for_an_incident_that_never_existed(calm):
    from backend.presentation import build_view

    for bucket in tenant_of(calm)["signalsHistory"][100:103]:
        bucket["requestErrors"] = int(bucket["requests"] * 0.02)
    view = build_view(calm, verdict(calm))
    assert "never needed an incident" in view["decision"]["reason"]
    assert "agent closed" not in view["decision"]["reason"]


# --- found while wiring the first real application to the tracker -------------------

def test_partial_evidence_can_convict_but_cannot_acquit(calm):
    """Too little of the fleet reports. If what we do see is fine: BLIND. If it is already broken: ACT NOW."""
    tenant_of(calm).update(serviceCoveragePct=60, servicesDark=1)
    assert verdict(calm)["verdict"] == "blind"

    set_errors(calm, 38.0, only="checkout")
    result = verdict(calm)
    assert (result["verdict"], result["trigger"]) == ("act_now", "users_broken")
    assert result["states"]["trust"] == "blind"


def test_a_disconnected_agent_convicts_nobody(calm):
    """There the data itself is stale, so a broken service in it proves nothing about now."""
    set_errors(calm, 38.0, only="checkout")
    calm["status"]["clusterAgentStats"][calm["tenant"]]["connected"] = False
    assert verdict(calm)["verdict"] == "blind"
