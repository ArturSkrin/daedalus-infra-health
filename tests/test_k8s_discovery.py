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


def test_an_api_that_does_not_answer_is_blindness(monkeypatch, tmp_path):
    def refuse(path, timeout):
        raise ConnectionRefusedError
    monkeypatch.setattr(k8s_source, "_get", refuse)
    assert k8s_source.discover(SKIP, TIER2, str(tmp_path), 1) is None


def test_bind_address_comes_from_the_interface():
    assert interface_address("lo") == "127.0.0.1"
    with pytest.raises(OSError):
        interface_address("wg-does-not-exist")         # no WireGuard: refuse to start rather than listen everywhere
