"""Workloads seen through the Kubernetes API from inside the cluster. Plain facts; never raises.

A target is a workload (Deployment, StatefulSet, DaemonSet), not a pod: pods come and go on every rollout and
eviction, a workload is what users depend on. It is up while at least one replica is ready. Pods only explain a
failure (CrashLoopBackOff, ImagePullBackOff) and lend their cgroup files. Read-only: get/list, nothing else.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from pathlib import Path

from adapter.docker_source import Container, _cgroup_dir, read_cgroup

SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
WORKLOADS = {
    "Deployment": "/apis/apps/v1/deployments",
    "StatefulSet": "/apis/apps/v1/statefulsets",
    "DaemonSet": "/apis/apps/v1/daemonsets",
}
# waiting reasons that mean the pod will not come up by itself
BROKEN = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "CreateContainerError",
          "InvalidImageName", "RunContainerError"}


def _get(path: str, timeout: float):
    host, port = os.environ["KUBERNETES_SERVICE_HOST"], os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    request = urllib.request.Request(f"https://{host}:{port}{path}", headers={
        "Authorization": f"Bearer {(SA / 'token').read_text().strip()}", "Accept": "application/json"})
    context = ssl.create_default_context(cafile=str(SA / "ca.crt"))
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:  # noqa: S310 - the API server's own address
        return json.loads(response.read())


def _owner(pod: dict) -> str | None:
    """The workload a pod belongs to: Deployment through its ReplicaSet, or the StatefulSet/DaemonSet directly."""
    for ref in pod["metadata"].get("ownerReferences") or []:
        if ref.get("kind") == "ReplicaSet":
            pod_hash = (pod["metadata"].get("labels") or {}).get("pod-template-hash")
            return ref["name"].removesuffix(f"-{pod_hash}") if pod_hash else re.sub(r"-[a-z0-9]+$", "", ref["name"])
        if ref.get("kind") in ("StatefulSet", "DaemonSet"):
            return ref["name"]
    return None


def _why(pod: dict) -> str | None:
    """What keeps a pod down, in the kubelet's words."""
    for status in (pod.get("status") or {}).get("containerStatuses") or []:
        waiting = (status.get("state") or {}).get("waiting") or {}
        if waiting.get("reason") in BROKEN:
            last = ((status.get("lastState") or {}).get("terminated") or {}).get("reason")
            return f"{waiting['reason']}" + (f" (last exit: {last})" if last else "")
    return None


def _cgroup(pod: dict, cgroup_root: str) -> dict | None:
    for status in (pod.get("status") or {}).get("containerStatuses") or []:
        container_id = (status.get("containerID") or "").rpartition("://")[2]
        directory = _cgroup_dir(Path(cgroup_root), container_id) if container_id and status.get("ready") else None
        if directory:
            return read_cgroup(directory)
    return None


# a host name in an env value or an argument: "api", "api.shop", "api.shop.svc.cluster.local", with an optional port
_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_HOST = re.compile(rf"(?<![\w.-])({_LABEL})(?:\.({_LABEL}))?(?:\.svc(?:\.cluster\.local)?)?(?::\d+)?(?![\w-])")


def _mentions(template: dict) -> list[str]:
    """Every literal string a pod template hands its containers: env values, command, args."""
    texts = []
    for container in (template.get("spec") or {}).get("containers") or []:
        texts += [e.get("value") for e in container.get("env") or [] if isinstance(e.get("value"), str)]
        texts += [a for a in (container.get("command") or []) + (container.get("args") or []) if isinstance(a, str)]
    return texts


def _backing(services: list[dict], workloads: list[tuple[str, dict, dict]]) -> dict[str, list[str]]:
    """"<ns>/<service>" -> the workloads whose pods the Service selects."""
    backing: dict[str, list[str]] = {}
    for svc in services:
        selector = (svc.get("spec") or {}).get("selector") or {}
        key = f"{svc['metadata']['namespace']}/{svc['metadata']['name']}"
        backing[key] = [name for name, labels, _ in workloads
                        if selector and name.startswith(f"{svc['metadata']['namespace']}/") and selector.items() <= labels.items()]
    return backing


def _edges(workloads: list[tuple[str, dict, dict]], backing: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    """Who calls whom, from Service names the workloads mention. Secrets are not read, so a URL kept in a Secret
    is not seen: this is a floor, never a full map. Empty when Services cannot be listed (older RBAC)."""
    calls = {}
    for name, _, template in workloads:
        namespace = name.split("/")[0]
        targets = set()
        for text in _mentions(template):
            for host, ns in _HOST.findall(text):
                for key in (f"{ns}/{host}" if ns else None, f"{namespace}/{host}"):
                    targets.update(w for w in backing.get(key or "", []) if w != name)
        calls[name] = tuple(sorted(targets))
    return calls


# Real traffic, from the ingress every site goes through. k3s ships Traefik with Prometheus metrics on :9100 of its
# pod; reached by pod IP from inside the cluster, so nothing new is exposed. Per Traefik service ("<ns>-<service>-
# <port name or number>@kubernetes"): requests by code, and a latency histogram in seconds. All cumulative.
TRAEFIK_METRICS_PORT = 9100
_SAMPLE = re.compile(r'^(traefik_service_requests_total|traefik_service_request_duration_seconds_bucket)\{([^}]*)\}\s+(\S+)$')
_PAIR = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def _scrape(ip: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(f"http://{ip}:{TRAEFIK_METRICS_PORT}/metrics", timeout=timeout) as response:  # noqa: S310 - a pod IP from the API
            return response.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None


def _traffic(pods: list[dict], services: list[dict], backing: dict[str, list[str]], timeout: float) -> dict[str, dict]:
    """Workload -> {requests, errors, durationBucketsMs}, the shape an app's own vitals endpoint reports. Empty when
    there is no Traefik, or its metrics are off: the services then keep their probes, as before."""
    ips = [p["status"]["podIP"] for p in pods
           if (p["metadata"].get("labels") or {}).get("app.kubernetes.io/name") == "traefik"
           and (p.get("status") or {}).get("phase") == "Running" and (p.get("status") or {}).get("podIP")]
    names: dict[str, str] = {}              # "<ns>-<service>-<port>" -> "<ns>/<service>"
    for svc in services:
        ns, name = svc["metadata"]["namespace"], svc["metadata"]["name"]
        for port in (svc.get("spec") or {}).get("ports") or []:
            for ref in (port.get("name"), port.get("port")):
                if ref not in (None, ""):
                    names[f"{ns}-{name}-{ref}"] = f"{ns}/{name}"
    out: dict[str, dict] = {}
    for ip in ips:
        for line in (_scrape(ip, timeout) or "").splitlines():
            match = _SAMPLE.match(line)
            if not match:
                continue
            labels = dict(_PAIR.findall(match[2]))
            service = names.get(labels.get("service", "").rpartition("@")[0])
            try:
                value = float(match[3])
            except ValueError:
                continue
            for workload in backing.get(service or "", []):
                slot = out.setdefault(workload, {"requests": 0.0, "errors": 0.0, "durationBucketsMs": {}})
                if match[1] == "traefik_service_requests_total":
                    slot["requests"] += value
                    # 5xx is the service failing a user; 4xx is the user's own mistake, code 0 a websocket closing
                    slot["errors"] += value if labels.get("code", "").startswith("5") else 0.0
                else:
                    le = labels.get("le", "")
                    key = "+Inf" if le == "+Inf" else f"{float(le) * 1000:g}"
                    slot["durationBucketsMs"][key] = slot["durationBucketsMs"].get(key, 0.0) + value
    return out


def discover(skip_namespaces: set[str], tier2_namespaces: set[str], cgroup_root: str, timeout: float) -> list[Container] | None:
    """Every workload in the cluster. None when the API cannot be asked: blindness, not an empty cluster."""
    try:
        pods: dict[str, list[dict]] = {}
        pod_items = _get("/api/v1/pods", timeout)["items"]
        for pod in pod_items:
            owner = _owner(pod)
            if owner:
                pods.setdefault(f"{pod['metadata']['namespace']}/{owner}", []).append(pod)
        found, templates = [], []
        for kind, path in WORKLOADS.items():
            for item in _get(path, timeout)["items"]:
                meta, spec, status = item["metadata"], item.get("spec") or {}, item.get("status") or {}
                if meta["namespace"] in skip_namespaces or (meta.get("labels") or {}).get("daedalus.ignore") == "true":
                    continue
                name = f"{meta['namespace']}/{meta['name']}"
                if kind == "DaemonSet":
                    desired, ready = status.get("desiredNumberScheduled") or 0, status.get("numberReady") or 0
                else:
                    desired, ready = spec.get("replicas", 1), status.get("readyReplicas") or 0
                mine = pods.get(name, [])
                if desired == 0:
                    ok, detail = True, "scaled to zero"
                elif ready > 0:
                    ok, detail = True, f"{ready}/{desired} ready"
                else:
                    reason = next((r for r in map(_why, mine) if r), None)
                    ok, detail = False, f"0/{desired} ready" + (f": {reason}" if reason else "")
                label = (meta.get("labels") or {}).get("daedalus.tier") or ""
                tier = int(label) if label.isdigit() else 2 if meta["namespace"] in tier2_namespaces else 1
                cgroup = next((c for c in (_cgroup(p, cgroup_root) for p in mine) if c), None)
                found.append(Container(name, tier, ok, detail, cgroup))
                template = spec.get("template") or {}
                templates.append((name, (template.get("metadata") or {}).get("labels") or {}, template))
        try:
            services = _get("/api/v1/services", timeout)["items"]
        except (OSError, ValueError, KeyError):
            services = []                       # older RBAC: no calls and no traffic, everything else as before
        backing = _backing(services, templates)
        calls = _edges(templates, backing)
        traffic = _traffic(pod_items, services, backing, timeout)
        return [Container(c.name, c.tier, c.ok, c.detail, c.cgroup, calls.get(c.name, ()), traffic.get(c.name)) for c in found]
    except (OSError, ValueError, KeyError):
        return None
