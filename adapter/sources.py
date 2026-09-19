"""The three ways to look at a target. Each returns plain facts and never raises."""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    reachable: bool        # False: the name does not resolve on our network, so we cannot see the service at all
    ok: bool               # answered, and not with a 5xx
    ms: float | None
    detail: str


def _unresolvable(error: BaseException) -> bool:
    reason = getattr(error, "reason", error)
    return isinstance(reason, socket.gaierror)


def http_probe(url: str, timeout: float, headers: dict[str, str] | None = None) -> Probe:
    request = urllib.request.Request(url, headers={"User-Agent": "daedalus-collector/1", **(headers or {})})
    context = ssl.create_default_context()
    if url.startswith("https://") and "." not in url.split("/")[2].split(":")[0]:
        # a compose-internal name with a self-signed certificate; public hosts keep full verification
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - URLs come from our own config
            response.read(256)
            return Probe(True, response.status < 500, (time.monotonic() - started) * 1000, f"HTTP {response.status}")
    except urllib.error.HTTPError as error:
        # 4xx still proves the service is alive and answering; only 5xx counts against it
        return Probe(True, error.code < 500, (time.monotonic() - started) * 1000, f"HTTP {error.code}")
    except Exception as error:  # noqa: BLE001 - every failure mode is a fact about the target, not a bug here
        if _unresolvable(error):
            return Probe(False, False, None, "name does not resolve on this network")
        return Probe(True, False, None, type(getattr(error, "reason", error)).__name__)


def tcp_probe(address: str, timeout: float) -> Probe:
    host, _, port = address.rpartition(":")
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return Probe(True, True, (time.monotonic() - started) * 1000, "accepting connections")
    except socket.gaierror:
        return Probe(False, False, None, "name does not resolve on this network")
    except Exception as error:  # noqa: BLE001
        return Probe(True, False, None, type(error).__name__)


def fetch_vitals(url: str, timeout: float, token: str | None) -> dict | None:
    """The in-app endpoint (integrations/eve-tools/vitals.ts). None when it is absent or unreadable."""
    request = urllib.request.Request(url, headers={"Accept": "application/json", **({"X-Vitals-Token": token} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
            return body if isinstance(body, dict) else None
    except Exception:  # noqa: BLE001
        return None
