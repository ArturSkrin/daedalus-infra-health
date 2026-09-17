"""Generate one mock JSON per scenario from a shared fleet fixture.

Each output file bundles the four Triage endpoints the Vitals screen reads
(status, incidents, applications, graph, analytics) in the shapes described in
vitals-metrics-catalog.md, plus an `expected` block with the verdict from
scenarios.md so that evaluate.py can check the rules against them.

Run:  python generate.py
"""
from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent
TENANT = "digital-purchases"
TZ = timezone(timedelta(hours=3))  # Europe/Kyiv, summer
WINDOW_S = 60
BUCKET_S = 300
BUCKETS_24H = 288

# ---------------------------------------------------------------- fixture ---

SERVICES = [
    # name,          tier, blast, rps
    ("api-gateway",   1, 0.71, 420),
    ("auth",          1, 0.55, 210),
    ("checkout",      1, 0.62,  85),
    ("payments",      1, 0.58,  60),
    ("catalog",       2, 0.31, 300),
    ("search",        2, 0.28, 150),
    ("cart",          2, 0.34,  90),
    ("notifications", 3, 0.12,  20),
    ("image-resizer", 3, 0.06,  40),
    ("reporting",     3, 0.09,   2),
    ("scheduler",     3, 0.05,   0),
    ("backup",        3, 0.04,   0),
]
EDGES = [
    ("api-gateway", "auth"), ("api-gateway", "checkout"), ("api-gateway", "catalog"),
    ("api-gateway", "search"), ("api-gateway", "cart"), ("cart", "checkout"),
    ("checkout", "payments"), ("checkout", "cart"), ("cart", "catalog"),
    ("payments", "notifications"), ("catalog", "image-resizer"),
    ("scheduler", "reporting"),
]
ERR_BASE = 0.20  # percent
WEEKS = ["2026-W33", "2026-W34", "2026-W35", "2026-W36"]
# weekly incident counts per service; column sums are 4, 3, 5, 4 -> median 4
WEEKLY = {
    "api-gateway": [1, 0, 1, 1], "auth": [0, 1, 1, 0], "checkout": [1, 1, 1, 1],
    "payments": [1, 0, 1, 1], "catalog": [0, 1, 0, 0], "search": [0, 0, 0, 0],
    "cart": [1, 0, 1, 1], "notifications": [0, 0, 0, 0], "image-resizer": [0, 0, 0, 0],
    "reporting": [0, 0, 0, 0], "scheduler": [0, 0, 0, 0], "backup": [0, 0, 0, 0],
}
PATTERNS = [
    {
        "id": "token-refresh-storm",
        "service": "payments",
        "steps": [
            "auth p99 rises above 400ms",
            "payments retries to auth double",
            "token cache hit rate drops below 60%",
            "payments 5xx on /oauth/token starts",
            "checkout error rate above 5%",
        ],
        "seenCount": 3,
        "avgLeadMs": 1_080_000,
    },
    {
        "id": "catalog-memory-creep",
        "service": "catalog",
        "steps": [
            "memReqPct above 85%",
            "memPsi above 1%",
            "GC pause warnings in logs",
            "OOM kill",
        ],
        "seenCount": 2,
        "avgLeadMs": 5_400_000,
    },
]


def ts(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def unix(dt: datetime) -> int:
    return int(dt.timestamp())


def diurnal(dt: datetime) -> float:
    """Traffic multiplier 0.55 .. 1.15 over the day."""
    h = dt.hour + dt.minute / 60
    return 0.85 + 0.30 * math.sin((h - 6) / 24 * 2 * math.pi)


def make_history(now: datetime, rng: random.Random, err_rate, missing_last=0,
                 signal_fn=None):
    """288 five-minute buckets ending at `now`. err_rate(dt) -> percent."""
    start = now - timedelta(seconds=BUCKET_S * BUCKETS_24H)
    total_rps = sum(s[3] for s in SERVICES)
    out = []
    for i in range(BUCKETS_24H - missing_last):
        t = start + timedelta(seconds=BUCKET_S * i)
        req = int(total_rps * BUCKET_S * diurnal(t) * rng.uniform(0.96, 1.04))
        e = err_rate(t) / 100
        errs = int(req * e * rng.uniform(0.9, 1.1))
        sig, noise = (signal_fn(t) if signal_fn else (rng.randint(0, 2), rng.randint(35, 65)))
        out.append({"t": ts(t), "requests": req, "requestErrors": errs,
                    "signal": sig, "noise": noise})
    return out


def make_apps(now: datetime, rng: random.Random, overrides: dict, stale_s=0):
    apps = []
    asof = unix(now) - (stale_s if stale_s else rng.randint(20, 55))
    for name, tier, blast, rps in SERVICES:
        o = overrides.get(name, {})
        err = o.get("errPct", round(rng.uniform(0.1, 0.3), 2))
        app = {
            "name": name,
            "tenant": TENANT,
            "ready": o.get("ready", True),
            "componentsReady": o.get("componentsReady", 3),
            "componentsTotal": 3,
            "observedAt": ts(datetime.fromtimestamp(asof, TZ)),
            "golden": {
                "reqPerSec": o.get("reqPerSec", rps),
                "errPct": err,
                "p99Ms": o.get("p99Ms", int(rng.uniform(120, 380))),
                "rateAsOfUnix": asof,
                "cpuPsiPct": o.get("cpuPsiPct", round(rng.uniform(0.0, 0.4), 2)),
                "memPsiPct": o.get("memPsiPct", round(rng.uniform(0.0, 0.3), 2)),
                "ioPsiPct": o.get("ioPsiPct", round(rng.uniform(0.0, 0.2), 2)),
                "oomKills": o.get("oomKills", 0),
                "saturationAsOfUnix": asof,
                "memPct": o.get("memPct", int(rng.uniform(35, 60))),
                "cpuPct": o.get("cpuPct", int(rng.uniform(15, 45))),
                "memReqPct": o.get("memReqPct", int(rng.uniform(50, 75))),
                "cpuReqPct": o.get("cpuReqPct", int(rng.uniform(30, 60))),
                "memNodePct": o.get("memNodePct", int(rng.uniform(8, 20))),
                "cpuNodePct": o.get("cpuNodePct", int(rng.uniform(5, 15))),
                "memBytes": o.get("memBytes", 512 * 1024 * 1024),
                "memRequestBytes": 768 * 1024 * 1024,
                "cpuCores": 0.4,
                "cpuRequestCores": 1.0,
                "utilizationAsOfUnix": asof,
            },
        }
        if rps == 0:
            # batch services: no request rate block at all (catalog: "omitted when nothing to report")
            for k in ("reqPerSec", "errPct", "p99Ms", "rateAsOfUnix"):
                app["golden"].pop(k)
        apps.append(app)
    return apps


def make_graph():
    calls = {s[0]: [] for s in SERVICES}
    called_by = {s[0]: [] for s in SERVICES}
    for a, b in EDGES:
        calls[a].append(b)
        called_by[b].append(a)
    nodes = [{"name": n, "tier": t, "blastRadius": b, "weight": round(b * 1.4, 2),
              "calls": calls[n], "calledBy": called_by[n]} for n, t, b, _ in SERVICES]
    return {"tenant": TENANT, "nodes": nodes,
            "edges": [{"from": a, "to": b} for a, b in EDGES]}


def make_analytics(precursor_matches):
    baselines = []
    for name, tier, blast, _ in SERVICES:
        counts = WEEKLY[name]
        baselines.append({
            "service": name,
            "mttrMean": 720_000 if tier == 1 else 1_500_000,
            "mttdMean": 45_000,
            "blastRadiusMean": blast,
            "reopenRate": 0.0,
            "incidentRateWeek": round(sum(counts) / len(counts), 2),
            "weeklyIncidentCounts": dict(zip(WEEKS, counts)),
        })
    return {"tenant": TENANT, "baselines": baselines, "patterns": PATTERNS,
            "precursorMatches": precursor_matches}


def base_tenant(history, events, by_type, open_now, sampled=0, auto=None, repeat=None,
                precision=(78, 31, 9), lead_ms=2_460_000, coverage=(100, 12, 0)):
    cov, services, dark = coverage
    t = {
        "services": services,
        "serviceCoveragePct": cov,
        "servicesDark": dark,
        "snrPct": round(100 * (events["signal"] + events["incident"]) /
                        max(1, events["signal"] + events["incident"] + events["noise"]), 1),
        "resolutionRatePct": 96,
        "predictionPrecisionPct": precision[0],
        "predictionHits": precision[1],
        "predictionMisses": precision[2],
        "predictionAvgLeadMs": lead_ms,
        "precursorCoveragePct": 71,
        "eventsPerIncident": 143,
        "sampledIncidents": sampled,
        "events": events,
        "signalsByType": by_type,
        "signalsHistory": history,
        "incidents": {"openNow": open_now},
    }
    if sampled:
        t["mttrMs"] = 690_000
        t["mttdMs"] = 41_000
        t["autoResolvedPct"] = auto
        t["repeatRatePct"] = repeat
    return t


def bundle(sid, title, now, story, expected, tenant, incidents, apps, precursors,
           agent_connected=True, last_msg=None, known=12, unmapped=0, unmapped_names=()):
    return {
        "scenario": sid,
        "title": title,
        "tenant": TENANT,
        "now": ts(now),
        "story": story,
        "expected": expected,
        "status": {
            "generatedAt": ts(now),
            "tenantStats": {"tenants": {TENANT: tenant}},
            "clusterAgentStats": {TENANT: {
                "cluster": "gke-eu-prod-1",
                "connected": agent_connected,
                "lastMessageUnix": unix(last_msg or now - timedelta(seconds=8)),
            }},
            "knownServices": known,
            "unmappedServices": unmapped,
            "unmappedNames": list(unmapped_names),
            "unmappedTruncated": False,
        },
        "incidents": incidents,
        "applications": apps,
        "graph": make_graph(),
        "analytics": make_analytics(precursors),
    }


def no_incidents():
    return {"tenant": TENANT,
            "incidentMetrics": {"criticalOpen": 0, "warningOpen": 0, "infoOpen": 0, "medianTTR": 0},
            "incidents": []}


def flat(_):
    return ERR_BASE


# -------------------------------------------------------------- scenarios ---

def s01():
    now = datetime(2026, 9, 14, 8, 30, tzinfo=TZ)
    rng = random.Random(1)
    hist = make_history(now, rng, flat)
    tenant = base_tenant(hist, {"noise": 14210, "signal": 96, "incident": 0, "unknown": 3, "drift": 0},
                         {"log": 61, "red": 0, "use": 9, "k8s": 26}, open_now=0)
    return bundle("s01_calm", "Quiet morning", now,
                  "Monday, 08:30. Nothing happened overnight.",
                  {"verdict": "all_clear", "reason": "all normal, nothing happened in the last day",
                   "states": {"users": "ok", "forecast": "clear", "trust": "full", "day": "quiet"}},
                  tenant, no_incidents(), make_apps(now, rng, {}), [])


def s02():
    now = datetime(2026, 9, 14, 13, 10, tzinfo=TZ)
    rng = random.Random(2)
    bump_start = now.replace(hour=9, minute=40)
    bump_end = now.replace(hour=9, minute=55)

    def err(t):
        return 1.4 if bump_start <= t < bump_end else ERR_BASE

    hist = make_history(now, rng, err)
    tenant = base_tenant(hist, {"noise": 15880, "signal": 142, "incident": 1, "unknown": 2, "drift": 1},
                         {"log": 88, "red": 31, "use": 7, "k8s": 41}, open_now=0,
                         sampled=1, auto=100, repeat=0)
    inc = {"tenant": TENANT,
           "incidentMetrics": {"criticalOpen": 0, "warningOpen": 0, "infoOpen": 0, "medianTTR": 720},
           "incidents": [{
               "id": "inc-2041", "service": "checkout", "severity": "warning", "status": "resolved",
               "firstSeen": ts(now.replace(hour=9, minute=40, second=12)),
               "resolvedAt": ts(now.replace(hour=9, minute=52, second=30)),
               "resolvedBy": "agent",
               "title": "checkout error rate 1.4% after rollout",
               "rca": "New pods served traffic before warm-up of the price cache; error rate returned to baseline once the cache filled.",
               "investigationPlan": ["confirm readiness probe waits for cache warm-up", "no action needed now"],
               "reopenCount": 0, "blastRadius": 0.62,
               "relatedEvents": ["AppDegraded checkout 09:40:12", "AppRecovered checkout 09:52:30",
                                 "GraphDrift checkout->cart 09:36"],
           }]}
    return bundle("s02_release_settled", "Release settled", now,
                  "checkout was rolled out at 09:35, errors spiked at 09:40, the agent closed the incident at 09:52. It is 13:10 now.",
                  {"verdict": "all_clear", "reason": "09:40 spike settled, the agent closed it on its own",
                   "states": {"users": "ok", "forecast": "clear", "trust": "full", "day": "settled"}},
                  tenant, inc, make_apps(now, rng, {}), [])


def s03():
    now = datetime(2026, 9, 14, 13, 10, tzinfo=TZ)
    rng = random.Random(3)
    rollout = now.replace(hour=11, minute=0)

    def err(t):
        return 0.46 if t >= rollout else ERR_BASE

    hist = make_history(now, rng, err)
    tenant = base_tenant(hist, {"noise": 15120, "signal": 210, "incident": 0, "unknown": 4, "drift": 2},
                         {"log": 140, "red": 58, "use": 6, "k8s": 33}, open_now=0)
    # tier-1 pinned to baseline so the fleet share is deterministic: 0.46 %
    apps = make_apps(now, rng, {"catalog": {"errPct": 1.0, "p99Ms": 410}, "cart": {"errPct": 1.5, "p99Ms": 530},
                                "api-gateway": {"errPct": 0.2}, "auth": {"errPct": 0.2},
                                "checkout": {"errPct": 0.2}, "payments": {"errPct": 0.2}})
    return bundle("s03_release_regressed", "Release regressed quietly", now,
                  "catalog and cart were rolled out at 11:00. Errors did not explode but have been steadily twice the norm for two hours. No incident was opened.",
                  {"verdict": "schedule", "reason": "errors twice the norm since 11:00 in catalog and cart",
                   "states": {"users": "ok", "forecast": "clear", "trust": "full", "day": "regressed"}},
                  tenant, no_incidents(), apps, [])


def s04():
    now = datetime(2026, 9, 15, 10, 0, tzinfo=TZ)
    rng = random.Random(4)
    hist = make_history(now, rng, flat)
    tenant = base_tenant(hist, {"noise": 13990, "signal": 118, "incident": 0, "unknown": 1, "drift": 0},
                         {"log": 44, "red": 0, "use": 52, "k8s": 22}, open_now=0)
    apps = make_apps(now, rng, {"catalog": {"memPsiPct": 2.4, "memReqPct": 93, "memPct": 71,
                                            "cpuPsiPct": 0.3, "ioPsiPct": 0.1, "oomKills": 0,
                                            "memBytes": 714 * 1024 * 1024}})
    return bundle("s04_memory_pressure", "Memory is saturating", now,
                  "Tuesday, 10:00. catalog is holding up, but memory is hitting its request and the kernel is stalling the process. No OOM kill yet.",
                  {"verdict": "schedule", "reason": "catalog: memory is saturating, no OOM kill yet",
                   "states": {"users": "ok", "forecast": "brewing", "trust": "full", "day": "quiet"}},
                  tenant, no_incidents(), apps, [])


def s05():
    now = datetime(2026, 9, 16, 15, 20, tzinfo=TZ)
    rng = random.Random(5)
    lost = now - timedelta(minutes=47)
    hist = make_history(now, rng, flat, missing_last=9)
    tenant = base_tenant(hist, {"noise": 12030, "signal": 80, "incident": 0, "unknown": 0, "drift": 0},
                         {"log": 40, "red": 0, "use": 4, "k8s": 18}, open_now=0)
    apps = make_apps(now, rng, {}, stale_s=47 * 60)
    return bundle("s05_agent_disconnected", "Cluster agent disconnected", now,
                  "Wednesday, 15:20. The cluster agent WebSocket dropped at 14:33. The core keeps serving the last known state and every counter looks great.",
                  {"verdict": "blind", "reason": "cluster agent disconnected for 47 min, the fleet is not visible",
                   "states": {"users": "unknown", "forecast": "unknown", "trust": "blind", "day": "unknown"}},
                  tenant, no_incidents(), apps, [], agent_connected=False, last_msg=lost)


def s06():
    now = datetime(2026, 9, 17, 11, 0, tzinfo=TZ)
    rng = random.Random(6)
    spike = now - timedelta(hours=1)

    def sig(t):
        if t >= spike:
            return (rng.randint(8, 18), rng.randint(680, 780))
        return (rng.randint(0, 2), rng.randint(35, 65))

    hist = make_history(now, rng, flat, signal_fn=sig)
    tenant = base_tenant(hist, {"noise": 22790, "signal": 264, "incident": 0, "unknown": 5, "drift": 0},
                         {"log": 8913, "red": 0, "use": 3, "k8s": 41}, open_now=0)
    # not in the catalog: the API keeps log volume only inside each event's `raw`, never per service
    tenant["topSignalSources"] = [{"service": "reporting", "type": "log", "count": 8913}]
    apps = make_apps(now, rng, {"reporting": {"errPct": 0.3}})
    return bundle("s06_log_spike", "Log spike with no impact", now,
                  "Thursday, 11:00. After a library upgrade, reporting writes 8.9k error lines an hour. Requests are going through.",
                  {"verdict": "all_clear", "reason": "reporting is noisy in logs, users are not affected",
                   "states": {"users": "ok", "forecast": "clear", "trust": "full", "day": "quiet"}},
                  tenant, no_incidents(), apps, [])


def s07():
    now = datetime(2026, 9, 18, 17, 45, tzinfo=TZ)
    rng = random.Random(7)
    outage = now - timedelta(minutes=4)

    def err(t):
        # only the still-open last bucket carries the outage
        return 3.05 if t >= now - timedelta(seconds=BUCKET_S) else ERR_BASE

    hist = make_history(now, rng, err)
    tenant = base_tenant(hist, {"noise": 15410, "signal": 171, "incident": 1, "unknown": 2, "drift": 0},
                         {"log": 210, "red": 96, "use": 5, "k8s": 37}, open_now=1,
                         sampled=1, auto=0, repeat=0)
    apps = make_apps(now, rng, {
        "checkout": {"errPct": 38.0, "p99Ms": 2900, "ready": False, "componentsReady": 2},
        "payments": {"errPct": 12.0, "p99Ms": 1400},
    })
    inc = {"tenant": TENANT,
           "incidentMetrics": {"criticalOpen": 1, "warningOpen": 0, "infoOpen": 0, "medianTTR": 0},
           "incidents": [{
               "id": "inc-2077", "service": "checkout", "severity": "critical", "status": "open",
               "firstSeen": ts(outage), "resolvedAt": None, "resolvedBy": None,
               "title": "checkout not ready: TLS handshake to payments fails",
               "rca": "Rotated certificate on payments is signed by a CA the checkout trust store does not contain; every call to payments fails with x509 unknown authority.",
               "investigationPlan": ["roll back payments cert secret to previous version",
                                     "add new CA to checkout trust bundle", "verify /health on checkout"],
               "reopenCount": 0, "blastRadius": 0.62,
               "relatedEvents": ["AppDegraded checkout", "RequestErrorAnomaly checkout POST /checkout/confirm",
                                 "RequestErrorAnomaly payments POST /charge", "Warning BackOff checkout-7d9f"],
           }]}
    return bundle("s07_outage", "Checkout is down", now,
                  "Friday, 17:45. A certificate rotation broke the checkout call to payments. A critical incident was opened 4 minutes ago.",
                  {"verdict": "act_now", "reason": "checkout is down, 2 more services will be hit",
                   "states": {"users": "broken", "forecast": "clear", "trust": "full", "day": "quiet"}},
                  tenant, inc, apps, [])


def s08():
    now = datetime(2026, 9, 19, 9, 0, tzinfo=TZ)
    rng = random.Random(8)
    hist = make_history(now, rng, flat)
    tenant = base_tenant(hist, {"noise": 9870, "signal": 61, "incident": 0, "unknown": 0, "drift": 0},
                         {"log": 30, "red": 0, "use": 3, "k8s": 12}, open_now=0,
                         coverage=(83, 12, 2))
    tenant["darkServices"] = [
        {"name": "scheduler", "lastEventAt": ts(now - timedelta(hours=6, minutes=4))},
        {"name": "backup", "lastEventAt": ts(now - timedelta(hours=6, minutes=11))},
    ]
    apps = make_apps(now, rng, {})
    apps = [a for a in apps if a["name"] not in ("scheduler", "backup")]
    return bundle("s08_dark_services", "Two services went silent", now,
                  "Saturday, 09:00. scheduler and backup have not sent a single event in 6 hours. Asleep or dead, unknown.",
                  {"verdict": "schedule", "reason": "scheduler and backup silent for 6 h: healthy or dead, unknown",
                   "states": {"users": "ok", "forecast": "clear", "trust": "partial", "day": "quiet"}},
                  tenant, no_incidents(), apps, [])


def s09():
    now = datetime(2026, 9, 21, 14, 5, tzinfo=TZ)
    rng = random.Random(9)
    hist = make_history(now, rng, flat)
    tenant = base_tenant(hist, {"noise": 14380, "signal": 133, "incident": 0, "unknown": 1, "drift": 0},
                         {"log": 72, "red": 11, "use": 6, "k8s": 29}, open_now=0,
                         lead_ms=1_080_000)
    apps = make_apps(now, rng, {"payments": {"errPct": 0.3, "memPsiPct": 0.4},
                                "auth": {"p99Ms": 430}})
    pre = [{"patternId": "token-refresh-storm", "service": "payments", "confidence": 0.84,
            "matchedSteps": 4, "totalSteps": 5,
            "matchedAt": ts(now - timedelta(minutes=3)),
            "matched": PATTERNS[0]["steps"][:4], "remaining": PATTERNS[0]["steps"][4:]}]
    return bundle("s09_precursor_imminent", "Agent sees a failure 18 minutes out", now,
                  "Monday, 14:05. Nothing is broken, but payments is walking the same chain of events that ended in a token refresh storm three times before. 4 of 5 steps are done.",
                  {"verdict": "act_now", "reason": "payments: agent sees 4 of 5 steps to a failure, usually ~18 min of warning",
                   "states": {"users": "ok", "forecast": "brewing", "trust": "full", "day": "quiet"}},
                  tenant, no_incidents(), apps, pre)


def s10():
    now = datetime(2026, 9, 21, 14, 5, tzinfo=TZ)
    rng = random.Random(10)
    hist = make_history(now, rng, flat)
    tenant = base_tenant(hist, {"noise": 6210, "signal": 58, "incident": 0, "unknown": 9, "drift": 3},
                         {"log": 31, "red": 4, "use": 2, "k8s": 21}, open_now=0,
                         precision=(42, 8, 11), lead_ms=900_000)
    apps = make_apps(now, rng, {})
    pre = [{"patternId": "token-refresh-storm", "service": "auth", "confidence": 0.90,
            "matchedSteps": 4, "totalSteps": 5,
            "matchedAt": ts(now - timedelta(minutes=2)),
            "matched": PATTERNS[0]["steps"][:4], "remaining": PATTERNS[0]["steps"][4:]}]
    return bundle("s10_low_precision", "Agent is confident but often wrong", now,
                  "Same match as S09, but the agent is in its second week here and got 8 of 19 predictions right.",
                  {"verdict": "all_clear", "reason": "all normal; agent suspects auth but is wrong more often than right",
                   "states": {"users": "ok", "forecast": "pressure", "trust": "full", "day": "quiet"}},
                  tenant, no_incidents(), apps, pre)


SCENARIOS = [s01, s02, s03, s04, s05, s06, s07, s08, s09, s10]


def main():
    index = []
    for fn in SCENARIOS:
        data = fn()
        path = OUT / f"{data['scenario']}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        index.append({"id": data["scenario"], "title": data["title"], "file": path.name,
                      "expected": data["expected"]["verdict"]})
        print(f"wrote {path.name}  ({path.stat().st_size // 1024} KB)")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote index.json")


if __name__ == "__main__":
    main()
