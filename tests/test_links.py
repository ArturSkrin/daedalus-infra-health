"""Evidence links: operator-supplied URL templates that take a human from a drill-in to a real tool."""
from __future__ import annotations

from urllib.parse import parse_qs, urljoin, urlsplit

import pytest

from backend.engine import verdict
from backend.presentation import build_view, evidence_links
from tests.conftest import load

GRAFANA = "grafana/d/tracker-logs/logs?var-project=eve-online-tools&var-service={service_re}&from=now-1h&to=now"


@pytest.fixture(autouse=True)
def no_templates(monkeypatch):
    for name in ("LOGS_URL_TEMPLATE", "TRACES_URL_TEMPLATE", "METRICS_URL_TEMPLATE"):
        monkeypatch.delenv(name, raising=False)


def test_nothing_configured_means_no_links():
    assert evidence_links("eve-tools", "docker-compose", "app") is None


def test_named_service_filters_the_logs_to_it(monkeypatch):
    monkeypatch.setenv("LOGS_URL_TEMPLATE", GRAFANA)
    [link] = evidence_links("eve-tools", None, "app")
    assert link["label"] == "Logs"
    assert parse_qs(urlsplit(link["url"]).query)["var-service"] == ["app"]


def test_no_named_service_shows_every_service_not_none(monkeypatch):
    """Trust and day name no service. An empty filter would match nothing; the regex placeholder matches all."""
    monkeypatch.setenv("LOGS_URL_TEMPLATE", GRAFANA)
    [link] = evidence_links("eve-tools", None, None)
    assert parse_qs(urlsplit(link["url"]).query)["var-service"] == [".+"]
    assert "var-service=.%2B" in link["url"]                       # "+" must not arrive as a space


@pytest.mark.parametrize("opened_at", ["http://localhost:8080/?live=1", "http://192.168.8.104:8080/?live=1&drill=users",
                                       "https://tracker.example.com/?scenario=s07_outage"])
def test_relative_template_follows_the_address_the_tracker_was_opened_at(monkeypatch, opened_at):
    monkeypatch.setenv("LOGS_URL_TEMPLATE", GRAFANA)
    [link] = evidence_links("eve-tools", None, "app")
    resolved = urlsplit(urljoin(opened_at, link["url"]))
    assert (resolved.scheme, resolved.netloc) == urlsplit(opened_at)[:2]
    assert resolved.path == "/grafana/d/tracker-logs/logs"


def test_empty_template_hides_the_button(monkeypatch):
    """How an overlay drops a link another overlay set: compose cannot unset a variable, only blank it."""
    monkeypatch.setenv("LOGS_URL_TEMPLATE", GRAFANA)
    monkeypatch.setenv("TRACES_URL_TEMPLATE", "")
    assert [link["label"] for link in evidence_links("eve-tools", None, "app")] == ["Logs"]


def test_values_are_url_quoted(monkeypatch):
    monkeypatch.setenv("LOGS_URL_TEMPLATE", "https://logs.example.com/?q={service}&t={tenant}")
    [link] = evidence_links("team a&b", None, "check out")
    assert link["url"] == "https://logs.example.com/?q=check%20out&t=team%20a%26b"


@pytest.mark.parametrize("broken", ["https://logs.example.com/?q={servce}", "https://logs.example.com/?q={", "x/{0}"])
def test_a_template_that_cannot_be_filled_in_is_skipped_not_fatal(monkeypatch, broken):
    monkeypatch.setenv("LOGS_URL_TEMPLATE", broken)
    monkeypatch.setenv("TRACES_URL_TEMPLATE", "traces/{service}")
    assert [link["label"] for link in evidence_links("eve-tools", None, "app")] == ["Traces"]

    data = load("s07_outage")
    view = build_view(data, verdict(data))                          # the whole screen still builds
    users = next(i for i in view["indicators"] if i["id"] == "users")
    assert [link["label"] for link in users["drill"]["links"]] == ["Traces"]


def test_drill_in_link_names_the_service_that_decided(monkeypatch):
    monkeypatch.setenv("LOGS_URL_TEMPLATE", GRAFANA)
    data = load("s07_outage")
    view = build_view(data, verdict(data))
    by_id = {i["id"]: i for i in view["indicators"]}
    assert "var-service=checkout" in by_id["users"]["drill"]["links"][0]["url"]
    assert "var-service=.%2B" in by_id["trust"]["drill"]["links"][0]["url"]
