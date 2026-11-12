"""The agent inside k3s: workloads read through the Kubernetes API, faked at k8s_source._get."""
from __future__ import annotations

import pytest

from adapter import k8s_source
from adapter.serve import interface_address

SKIP, TIER2 = frozenset({"kube-system"}), frozenset({"argocd"})


def _deployment(ns, name, replicas=1, ready=1, labels=None):
    return {"metadata": {"namespace": ns, "name": name, "labels": labels or {}},
            "spec": {"replicas": replicas}, "status": {"readyReplicas": ready} if ready else {}}


def _pod(ns, owner, pod_hash="7d4b9c", waiting=None, last=None):
    status = {"state": {"waiting": {"reason": waiting}} if waiting else {"running": {}}, "ready": not waiting,
              "containerID": "containerd://abc"}
    if last:
        status["lastState"] = {"terminated": {"reason": last}}
    return {"metadata": {"namespace": ns, "labels": {"pod-template-hash": pod_hash},
                         "ownerReferences": [{"kind": "ReplicaSet", "name": f"{owner}-{pod_hash}"}]},
            "status": {"containerStatuses": [status]}}


@pytest.fixture
def cluster(monkeypatch):
    world = {"/api/v1/pods": [], "/apis/apps/v1/deployments": [], "/apis/apps/v1/statefulsets": [], "/apis/apps/v1/daemonsets": []}
    monkeypatch.setattr(k8s_source, "_get", lambda path, timeout: {"items": world[path]})
    return world


def found(tmp_path):
    return {c.name: c for c in k8s_source.discover(SKIP, TIER2, str(tmp_path), 1)}


def test_a_workload_is_up_while_one_replica_is_ready(cluster, tmp_path):
    cluster["/apis/apps/v1/deployments"] = [_deployment("clc-claw", "clc-claw", replicas=2, ready=1)]
    cluster["/api/v1/pods"] = [_pod("clc-claw", "clc-claw"), _pod("clc-claw", "clc-claw", waiting="ContainerCreating")]
    claw = found(tmp_path)["clc-claw/clc-claw"]
    assert (claw.ok, claw.detail, claw.tier) == (True, "1/2 ready", 1)       # a rollout in progress, users still served


def test_crash_loop_is_named_from_the_pod(cluster, tmp_path):
    cluster["/apis/apps/v1/deployments"] = [_deployment("ccb", "api", ready=0)]
    cluster["/api/v1/pods"] = [_pod("ccb", "api", waiting="CrashLoopBackOff", last="OOMKilled")]
    api = found(tmp_path)["ccb/api"]
    assert (api.ok, api.detail) == (False, "0/1 ready: CrashLoopBackOff (last exit: OOMKilled)")


def test_namespaces_decide_what_is_watched_and_how_much_it_matters(cluster, tmp_path):
    cluster["/apis/apps/v1/deployments"] = [
        _deployment("kube-system", "coredns"), _deployment("argocd", "argocd-server"), _deployment("cloudflared", "cloudflared"),
        _deployment("ccb", "debug", labels={"daedalus.ignore": "true"}), _deployment("ccb", "worker", labels={"daedalus.tier": "2"})]
    seen = found(tmp_path)
    assert set(seen) == {"argocd/argocd-server", "cloudflared/cloudflared", "ccb/worker"}
    assert {n: c.tier for n, c in seen.items()} == {"argocd/argocd-server": 2, "cloudflared/cloudflared": 1, "ccb/worker": 2}


def test_scaled_to_zero_and_daemonsets(cluster, tmp_path):
    cluster["/apis/apps/v1/deployments"] = [_deployment("ccb", "batch", replicas=0, ready=0)]
    cluster["/apis/apps/v1/daemonsets"] = [{"metadata": {"namespace": "monitoring", "name": "node-agent"},
                                            "status": {"desiredNumberScheduled": 1, "numberReady": 0}}]
    seen = found(tmp_path)
    assert seen["ccb/batch"].ok
    assert (seen["monitoring/node-agent"].ok, seen["monitoring/node-agent"].detail) == (False, "0/1 ready")


def test_pod_cgroup_is_found_by_container_id(cluster, tmp_path):
    scope = tmp_path / "kubepods.slice" / "kubepods-burstable.slice" / "cri-containerd-abc.scope"
    scope.mkdir(parents=True)
    (scope / "memory.current").write_text("1048576\n")
    cluster["/apis/apps/v1/deployments"] = [_deployment("clc-claw", "clc-claw")]
    cluster["/api/v1/pods"] = [_pod("clc-claw", "clc-claw")]
    assert found(tmp_path)["clc-claw/clc-claw"].cgroup["memCurrentBytes"] == 1048576.0


def test_who_calls_whom_comes_from_service_names_in_env_and_args(cluster, tmp_path):
    def workload(name, app, env=(), args=()):
        d = _deployment("shop", name)
        d["spec"]["template"] = {"metadata": {"labels": {"app": app}},
                                 "spec": {"containers": [{"env": [{"name": k, "value": v} for k, v in env], "args": list(args)}]}}
        return d

    cluster["/apis/apps/v1/deployments"] = [
        workload("web", "web", env=[("API_URL", "http://api:8000/v1")]),
        workload("api", "api", env=[("DATABASE_URL", "postgres://u@db.shop.svc.cluster.local:5432/app"), ("MODE", "web")]),
        workload("db", "db", args=["-c", "max_connections=50"])]
    cluster["/api/v1/services"] = [{"metadata": {"namespace": "shop", "name": n}, "spec": {"selector": {"app": n}}}
                                   for n in ("web", "api", "db")]
    seen = found(tmp_path)
    assert seen["shop/web"].calls == ("shop/api",)
    assert seen["shop/api"].calls == ("shop/db", "shop/web")      # MODE=web names a Service too: a floor, read as a hint
    assert seen["shop/db"].calls == ()


TRAEFIK_METRICS = """\
# HELP traefik_service_requests_total How many HTTP requests processed on a service, partitioned by status code, protocol, and method.
traefik_service_requests_total{code="0",method="GET",protocol="websocket",service="ccb-ccb-http@kubernetes"} 200
traefik_service_requests_total{code="200",method="GET",protocol="http",service="ccb-ccb-http@kubernetes"} 15331
traefik_service_requests_total{code="404",method="GET",protocol="http",service="ccb-ccb-http@kubernetes"} 40
traefik_service_requests_total{code="502",method="POST",protocol="http",service="ccb-ccb-http@kubernetes"} 12
traefik_service_requests_total{code="200",method="GET",protocol="http",service="other-gone-80@kubernetes"} 9
traefik_service_request_duration_seconds_bucket{code="200",method="GET",protocol="http",service="ccb-ccb-http@kubernetes",le="0.1"} 15000
traefik_service_request_duration_seconds_bucket{code="200",method="GET",protocol="http",service="ccb-ccb-http@kubernetes",le="+Inf"} 15331
"""


def test_users_traffic_comes_from_traefik_by_service(cluster, monkeypatch, tmp_path):
    """Live on CCB: Traefik names the service "<ns>-<service>-<port name>"; 5xx fail users, 404 and websockets do not."""
    app = _deployment("ccb", "ccb")
    app["spec"]["template"] = {"metadata": {"labels": {"app": "ccb"}}, "spec": {"containers": [{}]}}
    cluster["/apis/apps/v1/deployments"] = [app]
    traefik = {"metadata": {"namespace": "kube-system", "labels": {"app.kubernetes.io/name": "traefik"}},
               "status": {"phase": "Running", "podIP": "10.42.0.7"}}
    cluster["/api/v1/pods"] = [_pod("ccb", "ccb"), traefik]
    cluster["/api/v1/services"] = [{"metadata": {"namespace": "ccb", "name": "ccb"},
                                    "spec": {"selector": {"app": "ccb"}, "ports": [{"name": "http", "port": 80}]}}]
    asked = []
    monkeypatch.setattr(k8s_source, "_scrape", lambda ip, timeout: asked.append(ip) or TRAEFIK_METRICS)
    traffic = found(tmp_path)["ccb/ccb"].traffic
    assert asked == ["10.42.0.7"]
    assert (traffic["requests"], traffic["errors"]) == (15583.0, 12.0)
    assert traffic["durationBucketsMs"] == {"100": 15000.0, "+Inf": 15331.0}


def test_without_traefik_metrics_services_keep_their_probes(cluster, monkeypatch, tmp_path):
    cluster["/apis/apps/v1/deployments"] = [_deployment("ccb", "ccb")]
    monkeypatch.setattr(k8s_source, "_scrape", lambda ip, timeout: None)
    assert found(tmp_path)["ccb/ccb"].traffic is None


def test_an_api_that_does_not_answer_is_blindness(monkeypatch, tmp_path):
    def refuse(path, timeout):
        raise ConnectionRefusedError
    monkeypatch.setattr(k8s_source, "_get", refuse)
    assert k8s_source.discover(SKIP, TIER2, str(tmp_path), 1) is None


def test_bind_address_comes_from_the_interface():
    assert interface_address("lo") == "127.0.0.1"
    with pytest.raises(OSError):
        interface_address("wg-does-not-exist")         # no WireGuard: refuse to start rather than listen everywhere
