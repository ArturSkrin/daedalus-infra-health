"""Checks from the outside: every public address the agents found, opened from the hub the way a user opens it.

The agents see a host from the inside: a site can be healthy there while users get nothing, because its domain
lapsed, a DNS record or a tunnel route went missing, Cloudflare is down, or a certificate expired. The addresses
come from the agents themselves (nginx server_name on Docker hosts, Ingress hosts on k3s), so a new or renamed
domain is followed without a list to keep by hand.

What becomes an incident on the service that serves the address:
  - it answers 5xx (502 from a proxy whose app is gone): critical at once, that is an answer, not a network blip;
  - it does not answer (timeout, DNS, TLS) twice in a row (a minute apart): critical;
  - once open it closes after two good answers in a row, so a site flapping between 502 and 200 stays open, and the
    5xx stays the headline when the next check only times out;
  - its certificate expires in under 14 days (warning) or 3 days (critical);
  - its domain registration expires in under 14 / 3 days, from RDAP (public, no key), checked once a day; TLDs
    without RDAP (.ru, .su, .рф and other ccTLDs) are asked over plain WHOIS (port 43). One lookup per registered
    domain, one at a time (rdap.org answers 429 to a burst), and a failed lookup is retried in an hour, not a day.
The incidents are added to the agent's own block as it is read (inject), so the verdict, the journal, the pushes
and /ops treat them like any other. Nothing here raises: a check that cannot run is a check that did not fail.
"""
from __future__ import annotations

import contextlib
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
OKS_TO_CLOSE = 2
CERT_EVERY_S = 6 * 3600
DOMAIN_EVERY_S = 24 * 3600
DOMAIN_RETRY_S = 3600
LOOKUP_GAP_S = 1.5                       # between two registry lookups: rdap.org rate-limits bursts
WARN_DAYS, CRIT_DAYS = 14, 3
USER_AGENT = "Daedalus-uptime/1.0"
# second-level suffixes where the registered domain is three labels (shop.example.co.uk -> example.co.uk)
_TWO_LEVEL = {"co.uk", "org.uk", "com.au", "co.jp", "com.br", "com.tr", "com.ua", "co.il", "msk.ru", "spb.ru", "com.ru"}

_lock = threading.Lock()
_state: dict[str, dict] = {}            # url -> what the last checks found
_where: dict[str, tuple[str, str]] = {}  # url -> (agent tenant, service), refreshed from the agents
_domains: dict[str, tuple[float | None, float]] = {}  # registered domain -> (expires unix, looked up at)
_whois_servers: dict[str, str | None] = {"ru": "whois.tcinet.ru", "su": "whois.tcinet.ru", "xn--p1ai": "whois.tcinet.ru"}
_lookup_lock = threading.Lock()
_EXPIRY_KEYS = ("registry expiry date", "registrar registration expiration date", "paid-till", "expiration date",
                "expiry date", "expires on", "expires", "expire", "renewal date")


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


def _parse_date(text: str) -> float | None:
    text = text.strip().replace("Z", "+00:00")
    for candidate in (text, text[:10], text[:10].replace(".", "-")):
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp()
    return None


def _rdap_expires(domain: str) -> float | None:
    request = urllib.request.Request(f"https://rdap.org/domain/{domain}",
                                     headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - the public RDAP bootstrap
            events = json.loads(response.read()).get("events") or []
    except (OSError, ValueError):
        return None                      # 404: the TLD has no RDAP; 429: rate limited
    for event in events:
        if event.get("eventAction") == "expiration" and event.get("eventDate"):
            return _parse_date(event["eventDate"])
    return None


def _whois(query: str, server: str) -> str:
    with socket.create_connection((server, 43), timeout=TIMEOUT_S) as conn:
        conn.sendall(f"{query}\r\n".encode())
        chunks = []
        while chunk := conn.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", "replace")


def whois_expires(text: str) -> float | None:
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() in _EXPIRY_KEYS and value.strip():
            found = _parse_date(value)
            if found:
                return found
    return None


def _whois_expires(domain: str) -> float | None:
    tld = domain.rsplit(".", 1)[-1]
    try:
        if tld not in _whois_servers:    # IANA names the registry's WHOIS server for every TLD
            refer = [line.split(":", 1)[1].strip() for line in _whois(tld, "whois.iana.org").splitlines()
                     if line.lower().startswith("whois:")]
            _whois_servers[tld] = refer[0] if refer and refer[0] else None
        server = _whois_servers[tld]
        return whois_expires(_whois(domain, server)) if server else None
    except (OSError, UnicodeError):
        return None


def _domain_days(host: str) -> float | None:
    """Days until the registration of the host's domain lapses: RDAP, else WHOIS; one lookup per domain a day."""
    domain = registered_domain(host)
    with contextlib.suppress(UnicodeError):  # .рф and other IDN names go to registries as punycode
        domain = domain.encode("idna").decode()
    with _lookup_lock:                   # one at a time: twenty subdomains at once is a burst rdap.org refuses
        expires, at = _domains.get(domain, (None, None))
        if at is None or time.time() - at >= (DOMAIN_EVERY_S if expires else DOMAIN_RETRY_S):
            expires = _rdap_expires(domain) or _whois_expires(domain)
            _domains[domain] = (expires, time.time())
            time.sleep(LOOKUP_GAP_S)
    return (expires - time.time()) / 86400 if expires else None


def check(url: str, now: float | None = None) -> dict:
    """One round for one address: open it; refresh the certificate and the domain when they are due."""
    now = time.time() if now is None else now
    with _lock:
        state = dict(_state.get(url) or {"fails": 0, "since": None})
    ok, detail = _open(url)
    server_error = not ok and detail.startswith("HTTP 5")
    state["fails"] = 0 if ok else state.get("fails", 0) + 1
    state["oks"] = state.get("oks", 0) + 1 if ok else 0
    if not ok and state["fails"] == 1 and not state.get("down"):
        state["since"] = now
    if server_error:
        state["error5xx"] = detail           # the site's own answer: a later timeout must not hide it
    if server_error or state["fails"] >= FAILS_TO_OPEN:
        state["down"] = True
    elif ok and (not state.get("down") or state["oks"] >= OKS_TO_CLOSE):
        state.update(down=False, since=None, error5xx=None)
    worst = state.get("error5xx")
    state["detail"] = detail if not worst or detail == worst else f"{worst}, last check: {detail}"
    host = urlsplit(url).hostname or ""
    def due(key: str, every: float) -> bool:
        return state.get(key) is None or now - state[key] >= every

    if ok and due("certAt", CERT_EVERY_S):
        state["certDays"], state["certAt"] = _cert_days(host), now
    if due("domainAt", DOMAIN_EVERY_S if state.get("domainDays") is not None else DOMAIN_RETRY_S):
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
        if state.get("down"):
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
        return [{"url": url, "host": tenant, "service": service,
                 "ok": not (_state.get(url) or {}).get("down") and (_state.get(url) or {}).get("fails", 0) == 0,
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
        _domains.clear()
