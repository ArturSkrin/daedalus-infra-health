"""The decision journal: only transitions are written, with the reason of the moment, and they survive a restart."""
from __future__ import annotations

import copy

import pytest

from backend import journal
from backend.engine import verdict
from backend.presentation import build_view
from tests.conftest import app_of, load, tenant_of


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    journal.reset()
    yield
    journal.reset()


def view_of(data: dict) -> dict:
    return build_view(data, verdict(data), mode="live", journal=[])


def outage(calm: dict) -> dict:
    d = copy.deepcopy(calm)
    d["incidents"] = load("s07_outage")["incidents"]
    for app in d["applications"]:
        if app["name"] == "checkout":
            app["golden"]["errPct"], app["ready"] = 38.0, False
    return d


def test_first_observation_is_one_started_event(calm):
    events = journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    assert [e["kind"] for e in events] == ["started"]
    assert events[0]["title"] == "Journal started: ALL CLEAR"


def test_nothing_changed_writes_nothing(calm):
    journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    later = copy.deepcopy(calm)
    for app in later["applications"]:
        for key in ("rateAsOfUnix", "saturationAsOfUnix"):
            if key in app["golden"]:
                app["golden"][key] += 40      # captions now say "data is 40 s older", states are the same
    assert journal.observe("t", view_of(later), at="2026-09-24T08:00:40+03:00") == []
    assert len(journal.events("t")) == 1


def test_an_outage_writes_the_word_the_indicator_and_the_incident(calm):
    journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    events = journal.observe("t", view_of(outage(calm)), at="2026-09-24T08:05:00+03:00")
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["verdict"]["title"] == "ALL CLEAR → ACT NOW"
    assert by_kind["verdict"]["detail"].startswith("checkout is down")
    assert by_kind["indicator"]["title"] == "Users now: Fine → Broken"
    assert by_kind["incident"]["title"] == "Incident opened: checkout"
    assert by_kind["incident"]["level"] == "bad"
    assert journal.events("t")[0]["at"] == "2026-09-24T08:05:00+03:00"            # newest first


def test_recovery_closes_the_incident_and_turns_the_word_back(calm):
    journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    journal.observe("t", view_of(outage(calm)), at="2026-09-24T08:05:00+03:00")
    events = journal.observe("t", view_of(calm), at="2026-09-24T08:20:00+03:00")
    titles = {e["title"] for e in events}
    assert {"ACT NOW → ALL CLEAR", "Users now: Broken → Fine", "Incident closed: checkout"} <= titles


def test_journal_survives_a_restart(calm):
    journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    journal.observe("t", view_of(outage(calm)), at="2026-09-24T08:05:00+03:00")
    before = journal.events("t")
    journal.reset()                                                       # the process died
    assert journal.events("t") == before
    assert journal.observe("t", view_of(outage(calm)), at="2026-09-24T08:06:00+03:00") == []   # and did not re-announce


def test_tenants_do_not_share_a_journal(calm):
    journal.observe("a", view_of(calm), at="2026-09-24T08:00:00+03:00")
    journal.observe("b", view_of(outage(calm)), at="2026-09-24T08:00:00+03:00")
    assert journal.events("a")[0]["title"] == "Journal started: ALL CLEAR"
    assert journal.events("b")[0]["title"] == "Journal started: ACT NOW"


def test_indicator_events_carry_the_caption_of_the_moment(calm):
    journal.observe("t", view_of(calm), at="2026-09-24T08:00:00+03:00")
    pressed = copy.deepcopy(calm)
    app_of(pressed, "catalog")["golden"].update(memPsiPct=2.4, memReqPct=93)
    events = journal.observe("t", view_of(pressed), at="2026-09-24T09:00:00+03:00")
    forecast = next(e for e in events if e["indicator"] == "forecast")
    assert forecast["title"] == "What's brewing: Clear → Brewing"
    assert forecast["detail"] == "catalog: memory is saturating, no OOM kill yet"


def test_demo_scenarios_get_a_timeline_read_off_the_data():
    data = load("s02_release_settled")
    view = build_view(data, verdict(data), mode="demo")
    assert view["journalSource"] == "scenario"
    titles = [e["title"] for e in view["journal"]]
    assert titles[0] == "Now: ALL CLEAR"
    assert "Incident closed: checkout" in titles and "Incident opened: checkout" in titles
    assert titles.index("Incident closed: checkout") < titles.index("Incident opened: checkout")   # newest first


def test_live_journal_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import live
    from backend.main import app

    source = copy.deepcopy(load("s07_outage"))

    def fake_get(path, tenant=None):
        return {"/v2/agent/status": source["status"], "/v2/agent/incidents": source["incidents"],
                "/v2/agent/applications": source["applications"], "/v2/agent/graph": source["graph"],
                "/v2/agent/analytics": source["analytics"]}[path]

    monkeypatch.setenv("TRIAGE_BASE_URL", "https://triage.invalid")
    monkeypatch.setattr(live, "_get", fake_get)
    live._cache.clear()
    client = TestClient(app)
    view = client.get("/api/live").json()
    assert view["journalSource"] == "live"
    assert view["journal"][0]["kind"] == "started"
    tenant_of(source)["signalsHistory"] = []                       # nothing that changes a state: no new event
    live._cache.clear()
    assert len(client.get("/api/live/journal").json()) == 1
