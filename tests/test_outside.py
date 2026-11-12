"""Public addresses: found by the agents (nginx in a container, k8s Ingress), checked from the hub from outside."""
from __future__ import annotations

import io
import tarfile

import pytest

from adapter import docker_source, k8s_source
from backend import external

NGINX = """
# the site
server {
    listen 80;
    server_name example.com www.example.com;   # both
    location / { proxy_pass http://web:3000; }
}
server { listen 80 default_server; server_name _; return 444; }
server { server_name localhost *.example.com ~^(?<sub>.+)\\.example\\.com$ 10.0.0.1; }
"""


def test_server_names_are_real_host_names_only():
    assert docker_source.server_names(NGINX) == ["example.com", "www.example.com"]


def _tar(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_an_nginx_container_tells_its_sites_through_the_docker_api(monkeypatch):
    docker_source._sites.clear()
    asked = []

    def raw(url, path, timeout):
        asked.append(path)
        if "conf.d" in path:
            return _tar({"conf.d/default.conf": NGINX})
        raise OSError("docker API: HTTP 404")           # no sites-enabled in the official image

    monkeypatch.setattr(docker_source, "_raw", raw)
    assert docker_source._nginx_urls("unix:///x", "abc", 1, now=1000) == ("https://example.com/", "https://www.example.com/")
    assert docker_source._nginx_urls("unix:///x", "abc", 1, now=1100) == ("https://example.com/", "https://www.example.com/")
    assert len(asked) == 2                              # the second read came from the cache


def test_ingress_hosts_become_the_workloads_addresses():
    ingresses = [
        {"metadata": {"namespace": "ccb", "annotations": {"daedalus.probe-path": "/health"}},
         "spec": {"rules": [{"host": "ccb.example.com", "http": {"paths": [{"backend": {"service": {"name": "ccb"}}}]}},
                            {"host": "*.example.com", "http": {"paths": [{"backend": {"service": {"name": "ccb"}}}]}}]}},
        {"metadata": {"namespace": "ccb", "annotations": {"daedalus.ignore": "true"}},
         "spec": {"rules": [{"host": "admin.example.com", "http": {"paths": [{"backend": {"service": {"name": "ccb"}}}]}}]}},
    ]
    assert k8s_source._public_urls(ingresses, {"ccb/ccb": ["ccb/ccb"]}) == {"ccb/ccb": ("https://ccb.example.com/health",)}


@pytest.fixture
def hub(monkeypatch):
    external.reset()
    answers = {}
    monkeypatch.setattr(external, "_open", lambda url: answers[url])
    monkeypatch.setattr(external, "_cert_days", lambda host: 60.0)
    monkeypatch.setattr(external, "_domain_days", lambda host: 200.0)
    raw = {"tenant": "ccb-k3s", "graph": {"nodes": [{"name": "ccb/ccb", "urls": ["https://ccb.example.com/"]}]},
           "incidents": {"incidents": [], "incidentMetrics": {"criticalOpen": 0, "warningOpen": 0}},
           "status": {"tenantStats": {"tenants": {"ccb-k3s": {"incidents": {"openNow": 0}}}}}}
    external.remember("ccb-k3s", raw)
    return answers, raw


def test_a_site_that_does_not_open_twice_is_a_critical_incident_of_its_service(hub):
    answers, raw = hub
    answers["https://ccb.example.com/"] = (False, "the name does not resolve (DNS)")
    external.check("https://ccb.example.com/", now=1000)
    assert external.inject(raw) == raw                  # one miss is not an outage yet
    external.check("https://ccb.example.com/", now=1060)
    out = external.inject(raw)
    [incident] = out["incidents"]["incidents"]
    assert (incident["service"], incident["severity"], incident["status"]) == ("ccb/ccb", "critical", "open")
    assert "does not open from the internet (the name does not resolve (DNS))" in incident["title"]
    assert out["incidents"]["incidentMetrics"]["criticalOpen"] == 1
    assert out["status"]["tenantStats"]["tenants"]["ccb-k3s"]["incidents"]["openNow"] == 1
    answers["https://ccb.example.com/"] = (True, "HTTP 302")         # a redirect to a login page is an answer
    external.check("https://ccb.example.com/", now=1120)
    assert external.inject(raw)["incidents"]["incidents"] == []


def test_a_certificate_or_domain_close_to_expiry_warns_then_pages(hub, monkeypatch):
    answers, raw = hub
    answers["https://ccb.example.com/"] = (True, "HTTP 200")
    monkeypatch.setattr(external, "_cert_days", lambda host: 9.4)
    monkeypatch.setattr(external, "_domain_days", lambda host: 1.2)
    external.check("https://ccb.example.com/", now=1000)
    found = {i["title"]: i["severity"] for i in external.inject(raw)["incidents"]["incidents"]}
    assert found == {"the certificate of ccb.example.com expires in 9 days": "warning",
                     "the domain of ccb.example.com expires in 1 days": "critical"}


def test_registered_domain_for_rdap():
    assert external.registered_domain("shop.ccb.example.com") == "example.com"
    assert external.registered_domain("www.example.co.uk") == "example.co.uk"
