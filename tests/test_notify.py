"""Pushes to a phone: which journal events become a notification, and that sending never gets in the way."""
from __future__ import annotations

import json

from backend import notify


def _event(kind, level, title, detail="why"):
    return {"at": "2026-11-07T21:00:00+00:00", "kind": kind, "indicator": None, "level": level, "title": title, "detail": detail}


def test_only_what_needs_a_person_is_sent():
    sent = notify.messages([
        _event("incident", "bad", "Incident opened: CCB:ccb/api", "ccb/api is not answering"),
        _event("incident", "warn", "Incident opened: Backup:job/dump"),
        _event("incident", "good", "Incident closed: CCB:ccb/api"),
        _event("verdict", "bad", "ALL CLEAR → ACT NOW"),
        _event("verdict", "good", "ACT NOW → ALL CLEAR"),
        _event("indicator", "warn", "What's brewing: Clear → Brewing"),
        _event("ack", "muted", "Accepted as expected: CCB:ccb/cron"),
        _event("started", "good", "Journal started: ALL CLEAR"),
    ])
    assert [(m["title"], m["priority"]) for m in sent] == [
        ("CCB:ccb/api", 5), ("Backup:job/dump", 3), ("CCB:ccb/api is back", 2), ("ALL CLEAR → ACT NOW", 4), ("ACT NOW → ALL CLEAR", 3)]


def test_a_storm_is_one_summary():
    storm = [_event("incident", "bad", f"Incident opened: CCB:svc-{i}") for i in range(9)]
    [summary] = notify.messages(storm)
    assert summary["title"] == "9 changes at once" and summary["priority"] == 5
    assert summary["message"].count("•") == 9


def test_off_without_a_topic(monkeypatch):
    monkeypatch.delenv("NTFY_URL", raising=False)
    assert notify.send([_event("verdict", "bad", "ALL CLEAR → ACT NOW")]) == 0


def test_posts_json_to_the_server_root_with_the_topic(monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.sh/daedalus-x7q")
    monkeypatch.setenv("NTFY_CLICK", "https://ops.example/ops")
    monkeypatch.setenv("NTFY_TOKEN", "tk_test")
    seen = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"{}"

    def fake_open(request, timeout):
        seen.update(url=request.full_url, body=json.loads(request.data), auth=request.get_header("Authorization"))
        return Reply()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_open)
    notify._post({"title": "CCB:ccb/api", "message": "down", "priority": 5, "tags": ["rotating_light"]})
    assert seen["url"] == "https://ntfy.sh/"
    assert seen["body"] == {"topic": "daedalus-x7q", "title": "Daedalus · CCB:ccb/api", "message": "down", "priority": 5,
                            "tags": ["rotating_light"], "click": "https://ops.example/ops"}
    assert seen["auth"] == "Bearer tk_test"


def test_an_unreachable_server_is_only_a_warning(monkeypatch):
    monkeypatch.setenv("NTFY_URL", "https://ntfy.invalid/topic")

    def refuse(request, timeout):
        raise OSError("no route")

    monkeypatch.setattr(notify.urllib.request, "urlopen", refuse)
    notify._post({"title": "x", "message": "y", "priority": 3, "tags": []})       # does not raise
