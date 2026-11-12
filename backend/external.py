"""Checks from the outside: every public address the agents found, opened from the hub the way a user opens it.

The agents see a host from the inside: a site can be healthy there while users get nothing, because its domain
lapsed, a DNS record or a tunnel route went missing, Cloudflare is down, or a certificate expired. The addresses
come from the agents themselves (nginx server_name on Docker hosts, Ingress hosts on k3s), so a new or renamed
domain is followed without a list to keep by hand.

What becomes an incident on the service that serves the address:
  - it does not answer, or answers 5xx, twice in a row (a minute apart): critical;
  - its certificate expires in under 14 days (warning) or 3 days (critical);
  - its domain registration expires in under 14 / 3 days, from RDAP (public, no key), checked once a day.
The incidents are added to the agent's own block as it is read (inject), so the verdict, the journal, the pushes
and /ops treat them like any other. Nothing here raises: a check that cannot run is a check that did not fail.
"""
from __future__ import annotations

import hashlib
import json
import logging
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from urllib.parse import urlsplit

log = logging.getLogger("daedalus.external")

EVERY_S = 60
TIMEOUT_S = 10
FAILS_TO_OPEN = 2
CERT_EVERY_S = 6 * 3600
DOMAIN_EVERY_S = 24 * 3600
WARN_DAYS, CRIT_DAYS = 14, 3
USER_AGENT = "Daedalus-uptime/1.0"
# second-level suffixes where the registered domain is three labels (shop.example.co.uk -> example.co.uk)
_TWO_LEVEL = {"co.uk", "org.uk", "com.au", "co.jp", "com.br", "com.tr", "com.ua", "co.il", "msk.ru", "spb.ru", "com.ru"}

_lock = threading.Lock()
_state: dict[str, dict] = {}            # url -> what the last checks found
_where: dict[str, tuple[str, str]] = {}  # url -> (agent tenant, service), refreshed from the agents


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None                      # a redirect to a login page is an answer; do not follow it off the site


_opener = urllib.request.build_opener(_NoRedirect)


def registered_domain(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    keep = 3 if ".".join(labels[-2:]) in _TWO_LEVEL else 2
    return ".".join(labels[-keep:])


def _open(url: str) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _opener.open(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - addresses our own agents reported
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        # 3xx (not followed), 401, 403, 404: the site is there and answered; 5xx: it is there and failing
        return error.code < 500, f"HTTP {error.code}"
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLError):
            return False, f"TLS: {reason.reason or reason}"
        if isinstance(reason, socket.gaierror):
            return False, "the name does not resolve (DNS)"
        return False, str(reason)
    except (TimeoutError, OSError) as error:
        return False, f"no answer in {TIMEOUT_S} s" if isinstance(error, TimeoutError) else str(error)


def _cert_days(host: str) -> float | None:
    try:
        with socket.create_connection((host, 443), timeout=TIMEOUT_S) as raw, \
                ssl.create_default_context().wrap_socket(raw, server_hostname=host) as tls:
            not_after = tls.getpeercert().get("notAfter")
        return (ssl.cert_time_to_seconds(not_after) - time.time()) / 86400 if not_after else None
    except (OSError, ValueError):
        return None                      # an unreachable or broken TLS shows up in the plain check already


def _domain_days(host: str) -> float | None:
    request = urllib.request.Request(f"https://rdap.org/domain/{registered_domain(host)}",
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - the public RDAP bootstrap
            events = json.loads(response.read()).get("events") or []
    except (OSError, ValueError):
        return None
    for event in events:
        if event.get("eventAction") == "expiration" and event.get("eventDate"):
            try:
                expires = datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
            except ValueError:
                return None
            return (expires.timestamp() - time.time()) / 86400
    return None


def check(url: str, now: float | None = None) -> dict:
    """One round for one address: open it; refresh the certificate and the domain when they are due."""
    now = time.time() if now is None else now
    with _lock:
        state = dict(_state.get(url) or {"fails": 0, "since": None})
    ok, detail = _open(url)
    state["fails"] = 0 if ok else state["fails"] + 1
    state["detail"] = detail
    if ok:
        state["since"] = None
    elif state["fails"] == 1:
        state["since"] = now
    host = urlsplit(url).hostname or ""
    def due(key: str, every: float) -> bool:
        return state.get(key) is None or now - state[key] >= every

    if ok and due("certAt", CERT_EVERY_S):
        state["certDays"], state["certAt"] = _cert_days(host), now
    if due("domainAt", DOMAIN_EVERY_S):
        state["domainDays"], state["domainAt"] = _domain_days(host), now
    with _lock:
        _state[url] = state
    return state


def remember(tenant: str, raw: dict) -> None:
    """Note which addresses an agent reports, and for which of its services."""
    with _lock:
        for url in [u for u, (t, _) in _where.items() if t == tenant]:
            del _where[url]
        for node in (raw.get("graph") or {}).get("nodes") or []:
            for url in node.get("urls") or []:
                if isinstance(url, str) and url.startswith("https://"):
                    _where[url] = (tenant, node.get("name"))


def _iso(unix: float) -> str:
    return datetime.fromtimestamp(unix, UTC).astimezone().isoformat(timespec="seconds")


def problems(tenant: str) -> list[dict]:
    """Open incidents for this agent's services, from the last checks of their addresses."""
    found = []
    with _lock:
        rows = [(url, service, dict(_state[url])) for url, (t, service) in _where.items() if t == tenant and url in _state]
    for url, service, state in rows:
        host = urlsplit(url).hostname or url
        key = hashlib.sha1(url.encode()).hexdigest()[:10]
        if state["fails"] >= FAILS_TO_OPEN:
            found.append((f"ext-{key}", service, "critical", f"{url} does not open from the internet ({state['detail']})", state["since"],
                          f"curl -sSI {url}"))
        for what, days in (("certificate", state.get("certDays")), ("domain", state.get("domainDays"))):
            if isinstance(days, (int, float)) and days < WARN_DAYS:
                text = f"the {what} of {host} expires in {max(0, round(days))} days" if days > 0 else f"the {what} of {host} has expired"
                step = "renew it at the registrar" if what == "domain" else f"openssl s_client -connect {host}:443 -servername {host}"
                found.append((f"ext-{what}-{key}", service, "critical" if days < CRIT_DAYS else "warning", text,
                              state.get("certAt" if what == "certificate" else "domainAt"), step))
    return [{"id": incident_id, "service": service, "severity": severity, "status": "open", "title": title,
             "reopens": 0, "firstSeen": _iso(since or time.time()), "resolvedAt": None, "resolvedBy": None,
             "blastRadius": 0, "rca": "Seen from the hub over the public internet, the way a user reaches the site.",
             "investigationPlan": [step], "relatedEvents": []}
            for incident_id, service, severity, title, since, step in found]


def inject(raw: dict) -> dict:
    """The agent's bundle with the outside problems of its services added as open incidents."""
    if not isinstance(raw, dict) or "tenant" not in raw:
        return raw
    remember(raw["tenant"], raw)
    extra = problems(raw["tenant"])
    if not extra:
        return raw
    block = raw.get("incidents") if isinstance(raw.get("incidents"), dict) else {}
    metrics = dict(block.get("incidentMetrics") or {})
    for incident in extra:
        key = "criticalOpen" if incident["severity"] == "critical" else "warningOpen"
        metrics[key] = int(metrics.get(key) or 0) + 1
    out = {**raw, "incidents": {**block, "incidents": [*(block.get("incidents") or []), *extra], "incidentMetrics": metrics}}
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    tenants = (status.get("tenantStats") or {}).get("tenants") or {}
    tenant = tenants.get(raw["tenant"]) if isinstance(tenants, dict) else None
    if isinstance(tenant, dict):
        opened = int((tenant.get("incidents") or {}).get("openNow") or 0) + len(extra)
        tenant = {**tenant, "incidents": {**(tenant.get("incidents") or {}), "openNow": opened}}
        out["status"] = {**status, "tenantStats": {**status["tenantStats"], "tenants": {**tenants, raw["tenant"]: tenant}}}
    return out


def urls() -> list[str]:
    with _lock:
        return sorted(_where)


def status() -> list[dict]:
    """Every address and what its last check found, for the screen."""
    with _lock:
        return [{"url": url, "host": tenant, "service": service, "ok": (_state.get(url) or {}).get("fails", 0) == 0,
                 "detail": (_state.get(url) or {}).get("detail"), "certDays": (_state.get(url) or {}).get("certDays"),
                 "domainDays": (_state.get(url) or {}).get("domainDays")}
                for url, (tenant, service) in sorted(_where.items())]


def watch(stop: threading.Event, refresh) -> None:
    """Every minute: ask the agents for their addresses (refresh), then check them all, a few at a time."""
    while not stop.is_set():
        try:
            refresh()
            targets = urls()
            if targets:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(check, targets))
        except Exception:
            log.exception("outside checks failed")
        stop.wait(EVERY_S)


def reset() -> None:
    """Tests only."""
    with _lock:
        _state.clear()
        _where.clear()
