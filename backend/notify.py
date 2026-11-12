"""Push to a phone through ntfy (ntfy.sh or a self-hosted server) when something changes that a person must know.

The journal already turns every poll into events, and its watcher runs whether or not anyone has the page open;
this sends some of those events on. Only what calls for a person: an incident opening (urgent when critical),
the verdict getting worse, and the all-clear when it comes back. Indicators moving and acks stay on the screen.

Configured by environment, off when NTFY_URL is not set:
  NTFY_URL    https://ntfy.sh/<topic>, the topic URL the phone subscribes to (a long random topic is the password)
  NTFY_TOKEN  an access token, for a server with access control (optional)
  NTFY_CLICK  where tapping the notification leads, e.g. https://ops.example.com/ops (optional)
Sending never raises and never blocks the watcher: a phone that cannot be reached must not stop the journal.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from urllib.parse import urlsplit

log = logging.getLogger("daedalus.notify")

MAX_PER_ROUND = 5           # a restart of half the fleet is one summary, not twenty buzzes
RANK = {"good": 0, "muted": 0, "warn": 1, "bad": 2}


def configured() -> bool:
    return bool(os.environ.get("NTFY_URL"))


def worth_sending(event: dict) -> dict | None:
    """The message for one journal event, or None when it is only for the screen."""
    kind, level = event.get("kind"), event.get("level")
    if kind == "incident" and event["title"].startswith("Incident opened"):
        urgent = level == "bad"
        return {"title": event["title"].replace("Incident opened: ", ""), "message": event["detail"],
                "priority": 5 if urgent else 3, "tags": ["rotating_light"] if urgent else ["warning"]}
    if kind == "incident":
        return {"title": event["title"].replace("Incident closed: ", "") + " is back", "message": event["detail"],
                "priority": 2, "tags": ["white_check_mark"]}
    if kind == "verdict":
        better = RANK.get(level, 1) == 0
        return {"title": event["title"], "message": event["detail"], "priority": 3 if better else 4,
                "tags": ["green_circle"] if better else ["red_circle" if level == "bad" else "yellow_circle"]}
    return None


def messages(events: list[dict]) -> list[dict]:
    chosen = [m for m in map(worth_sending, events) if m]
    if len(chosen) <= MAX_PER_ROUND:
        return chosen
    top = max(m["priority"] for m in chosen)
    return [{"title": f"{len(chosen)} changes at once", "priority": top, "tags": ["rotating_light"] if top == 5 else ["warning"],
             "message": "\n".join(f"• {m['title']}" for m in chosen[:12]) + ("\n…" if len(chosen) > 12 else "")}]


def _post(message: dict) -> None:
    url = os.environ["NTFY_URL"].rstrip("/")
    parts = urlsplit(url)
    # JSON publishing to the server root: titles carry → and service names, which HTTP headers cannot
    body = {"topic": parts.path.strip("/"), **message, "title": f"Daedalus · {message['title']}"}
    if os.environ.get("NTFY_CLICK"):
        body["click"] = os.environ["NTFY_CLICK"]
    headers = {"Content-Type": "application/json"}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    request = urllib.request.Request(f"{parts.scheme}://{parts.netloc}/", data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - the operator's own ntfy server
            response.read()
    except (OSError, ValueError) as error:
        log.warning("ntfy: could not send %r: %s", message["title"], error)


def send(events: list[dict]) -> int:
    """Send what is worth it in the background. Returns how many messages went out."""
    if not configured():
        return 0
    batch = messages(events)
    if batch:
        threading.Thread(target=lambda: [_post(m) for m in batch], name="ntfy", daemon=True).start()
    return len(batch)
