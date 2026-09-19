"""The catalog says the core omits fields it has nothing to report for.

Whatever is missing or malformed, the engine must still decide and the view
must still build. A 500 on a missing field would contradict the thesis of the
whole project: "missing" and "zero" are different things.
"""
from __future__ import annotations

import copy

import pytest

from backend.engine import verdict
from backend.presentation import build_view
from tests.conftest import load, tenant_of

VERDICTS = {"all_clear", "schedule", "act_now", "blind"}
SATURATION_KEYS = ("memPsiPct", "cpuPsiPct", "ioPsiPct", "oomKills", "saturationAsOfUnix")


def _pop_each(items, *keys):
    for item in items:
        for key in keys:
            item.pop(key, None)


def _goldens(d):
    return [a["golden"] for a in d["applications"]]


MUTATIONS = {
    "analytics_without_precursors": lambda d: d["analytics"].pop("precursorMatches"),
    "analytics_without_baselines": lambda d: d["analytics"].pop("baselines"),
    "analytics_empty": lambda d: d.update(analytics={}),
    "analytics_missing": lambda d: d.pop("analytics"),
    "graph_empty": lambda d: d.update(graph={}),
    "graph_missing": lambda d: d.pop("graph"),
    "node_without_tier": lambda d: _pop_each(d["graph"]["nodes"], "tier"),
    "node_without_blast_radius": lambda d: _pop_each(d["graph"]["nodes"], "blastRadius"),
    "incidents_without_metrics": lambda d: d["incidents"].pop("incidentMetrics"),
    "incidents_without_list": lambda d: d["incidents"].pop("incidents"),
    "incidents_missing": lambda d: d.pop("incidents"),
    "incident_without_first_seen": lambda d: _pop_each(d["incidents"]["incidents"], "firstSeen"),
    "incident_without_status_title": lambda d: _pop_each(d["incidents"]["incidents"], "status", "title"),
    "app_without_golden": lambda d: _pop_each(d["applications"], "golden"),
    "app_rate_without_err_pct": lambda d: _pop_each(_goldens(d), "errPct"),
    "app_err_pct_null": lambda d: [g.update(errPct=None) for g in _goldens(d)],
    "app_err_pct_string": lambda d: [g.update(errPct="n/a") for g in _goldens(d)],
    "app_without_saturation": lambda d: _pop_each(_goldens(d), *SATURATION_KEYS),
    "applications_empty": lambda d: d.update(applications=[]),
    "applications_wrapped_in_object": lambda d: d.update(applications={"applications": d["applications"]}),
    "tenant_without_history": lambda d: tenant_of(d).pop("signalsHistory"),
    "bucket_without_request_errors": lambda d: _pop_each(tenant_of(d)["signalsHistory"], "requestErrors"),
    "bucket_without_timestamp": lambda d: _pop_each(tenant_of(d)["signalsHistory"], "t"),
    "tenant_without_prediction_fields": lambda d: _pop_each(
        [tenant_of(d)], "predictionHits", "predictionMisses", "predictionPrecisionPct", "predictionAvgLeadMs"),
    "tenant_without_coverage": lambda d: tenant_of(d).pop("serviceCoveragePct"),
    "tenant_missing": lambda d: d["status"]["tenantStats"]["tenants"].pop(d["tenant"]),
    "status_without_agent_stats": lambda d: d["status"].pop("clusterAgentStats"),
    "agent_stats_keyed_by_cluster": lambda d: d["status"].update(
        clusterAgentStats={"gke-eu-prod-1": {"tenant": d["tenant"], "connected": True}}),
    "status_empty": lambda d: d.update(status={}),
    "now_without_timezone": lambda d: d.update(now=d["now"][:19]),
    "now_missing": lambda d: d.pop("now"),
    "precursor_with_zero_steps": lambda d: d["analytics"].update(
        precursorMatches=[{"service": "payments", "confidence": 0.9, "matchedSteps": 0, "totalSteps": 0}]),
    "precursor_for_unknown_service": lambda d: d["analytics"].update(
        precursorMatches=[{"service": "ghost", "confidence": 0.9, "matchedSteps": 4, "totalSteps": 5}]),
    "everything_missing": lambda d: [d.pop(k) for k in ("status", "incidents", "applications", "graph", "analytics")],
}


@pytest.mark.parametrize("scenario_id", ["s01_calm", "s07_outage"])
@pytest.mark.parametrize("name", MUTATIONS)
def test_never_crashes_on_incomplete_data(scenario_id: str, name: str):
    data = copy.deepcopy(load(scenario_id))
    data.pop("expected")
    MUTATIONS[name](data)

    result = verdict(data)
    view = build_view(data, result, mode="live")

    assert result["verdict"] in VERDICTS
    assert view["decision"]["reason"]
    assert len(view["indicators"]) == 4


def test_lost_tenant_is_blind_not_calm(calm):
    calm["status"]["tenantStats"]["tenants"].pop(calm["tenant"])
    assert verdict(calm)["verdict"] == "blind"


def test_nothing_at_all_is_blind():
    assert verdict({})["verdict"] == "blind"


def test_open_critical_incident_survives_missing_summary(calm):
    """criticalOpen omitted by the core: the open incident list still drives ACT NOW."""
    outage = load("s07_outage")
    calm["incidents"] = {"incidents": outage["incidents"]["incidents"]}
    result = verdict(calm)
    assert (result["verdict"], result["trigger"]) == ("act_now", "critical_incident")


def test_unreported_agent_link_with_fresh_data_is_not_blind(calm):
    calm["status"].pop("clusterAgentStats")
    assert verdict(calm)["verdict"] == "all_clear"


def test_unreported_agent_link_without_fresh_data_is_blind(calm):
    calm["status"].pop("clusterAgentStats")
    for golden in _goldens(calm):
        if "rateAsOfUnix" in golden:
            golden["rateAsOfUnix"] -= 3600
    assert verdict(calm)["verdict"] == "blind"


def test_missing_resource_data_is_not_read_as_no_pressure(calm):
    """Absent PSI means "not measured". It must not look like a clear forecast."""
    _pop_each(_goldens(calm), *SATURATION_KEYS)
    result = verdict(calm)
    assert result["states"]["forecast"] == "unknown"
    assert result["detail"]["trust"]["reasons"] == ["no_resource_data"]
    assert result["verdict"] == "schedule"
