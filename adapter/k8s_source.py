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


def _edges(workloads: list[tuple[str, dict, dict]], timeout: float) -> dict[str, tuple[str, ...]]:
    """Who calls whom, from Service names the workloads mention. Secrets are not read, so a URL kept in a Secret
    is not seen: this is a floor, never a full map. Empty when Services cannot be listed (older RBAC)."""
    try:
        services = _get("/api/v1/services", timeout)["items"]
    except (OSError, ValueError, KeyError):
        return {}
    backing: dict[str, list[str]] = {}          # "<ns>/<service>" -> workloads whose pods it selects
    for svc in services:
        selector = (svc.get("spec") or {}).get("selector") or {}
        key = f"{svc['metadata']['namespace']}/{svc['metadata']['name']}"
        backing[key] = [name for name, labels, _ in workloads
                        if selector and name.startswith(f"{svc['metadata']['namespace']}/") and selector.items() <= labels.items()]
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


def discover(skip_namespaces: set[str], tier2_namespaces: set[str], cgroup_root: str, timeout: float) -> list[Container] | None:
    """Every workload in the cluster. None when the API cannot be asked: blindness, not an empty cluster."""
    try:
        pods: dict[str, list[dict]] = {}
        for pod in _get("/api/v1/pods", timeout)["items"]:
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
        calls = _edges(templates, timeout)
        return [Container(c.name, c.tier, c.ok, c.detail, c.cgroup, calls.get(c.name, ())) for c in found]
    except (OSError, ValueError, KeyError):
        return None
