"""Reference implementation of the five indicators from metrics_spec.md.

Reads every scenario JSON in this folder, derives the four indicator states and
the verdict, and compares them with the `expected` block. Exit code 1 if any
scenario disagrees. The prototype should reproduce exactly these rules.

Run:  python evaluate.py            # all scenarios
      python evaluate.py s03        # one scenario, with the derived numbers
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
FRESH_S = 300           # 5 agent windows of 60 s
DAY_FLOOR_PCT = 0.3     # lowered from 0.5 after scenario S03
MIN_BUCKETS = 230       # 80 % of 288
RECENT_BUCKETS = 24     # last 2 h; was 6 h until scenario S03 showed a 2 h regression diluted away


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ------------------------------------------------------------ indicator 4 ---

def trust(d: dict) -> tuple[str, dict]:
    now = parse(d["now"]).timestamp()
    tenant = d["status"]["tenantStats"]["tenants"].get(d["tenant"])
    agent = d["status"]["clusterAgentStats"].get(d["tenant"], {})
    if tenant is None:
        return "Наосліп", {"why": "tenant missing"}
    if not agent.get("connected", False):
        mins = int((now - agent.get("lastMessageUnix", now)) / 60)
        return "Наосліп", {"why": f"agent disconnected {mins} min"}
    if tenant.get("services", 0) == 0:
        return "Наосліп", {"why": "services = 0"}

    cov = tenant.get("serviceCoveragePct", 0)
    dark = tenant.get("servicesDark", 0)
    unmapped = d["status"].get("unmappedServices", 0)

    total = fresh = 0.0
    for a in d["applications"]:
        g = a["golden"]
        if "reqPerSec" not in g:
            continue
        total += g["reqPerSec"]
        if now - g.get("rateAsOfUnix", 0) <= FRESH_S:
            fresh += g["reqPerSec"]
    fresh_share = 100 * fresh / total if total else 0
    info = {"coverage": cov, "dark": dark, "unmapped": unmapped, "freshShare": round(fresh_share, 1)}

    if cov < 80 or dark >= 3:
        return "Наосліп", info
    if cov < 95 or 1 <= dark <= 2 or unmapped > 0 or fresh_share < 90:
        return "Частково", info
    return "Повна", info


# ------------------------------------------------------------ indicator 2 ---

def users(d: dict) -> tuple[str, dict]:
    now = parse(d["now"]).timestamp()
    nodes = {n["name"]: n for n in d["graph"]["nodes"]}
    num = den = 0.0
    affected, tier1_broken, tier1_hurt = [], [], []
    for a in d["applications"]:
        g = a["golden"]
        if "reqPerSec" not in g or now - g.get("rateAsOfUnix", 0) > FRESH_S:
            continue
        rps, err = g["reqPerSec"], g["errPct"]
        num += rps * err / 100
        den += rps
        n = nodes.get(a["name"], {"tier": 3, "blastRadius": 0})
        if err >= 1:
            affected.append(a["name"])
        if n["tier"] == 1 and (err >= 5 or not a.get("ready", True)):
            tier1_broken.append(a["name"])
        elif n["tier"] == 1 and err >= 1:
            tier1_hurt.append(a["name"])
    if den == 0:
        return "—", {"why": "no fresh rate data"}
    share = 100 * num / den
    # max, not sum: blastRadius values of neighbouring services overlap
    blast = max((nodes[s]["blastRadius"] for s in affected if s in nodes), default=0)
    info = {"failingShare": round(share, 2), "affected": affected, "blastMax": round(blast, 2)}
    if share >= 5 or tier1_broken:
        info["tier1Broken"] = tier1_broken
        return "Зламано", info
    if share >= 0.5 or tier1_hurt:
        info["escalate"] = blast >= 0.5
        return "Страждають", info
    return "Добре", info


# ------------------------------------------------------------ indicator 3 ---

def forecast(d: dict) -> tuple[str, dict]:
    now = parse(d["now"]).timestamp()
    tenant = d["status"]["tenantStats"]["tenants"][d["tenant"]]
    nodes = {n["name"]: n for n in d["graph"]["nodes"]}
    hits, misses = tenant.get("predictionHits", 0), tenant.get("predictionMisses", 0)
    precision = tenant.get("predictionPrecisionPct")
    lead_ms = tenant.get("predictionAvgLeadMs") if hits else None
    info = {"precision": precision, "leadMin": round(lead_ms / 60000) if lead_ms else None}

    level, service = "Чисто", None
    best = 0.0
    for m in d["analytics"].get("precursorMatches", []):
        c = m["confidence"] if m["matchedSteps"] / m["totalSteps"] >= 0.5 else m["confidence"] * 0.5
        if c > best:
            best, service = c, m["service"]
    if best >= 0.7:
        level = "Назріває"
    elif best >= 0.5:
        level = "Тисне"
    info["precursorLevel"] = round(best, 2)

    pressure = []
    for a in d["applications"]:
        g = a["golden"]
        if now - g.get("saturationAsOfUnix", 0) > FRESH_S:
            continue
        if (g.get("memPsiPct", 0) >= 1 and g.get("memReqPct", 0) >= 90) or g.get("oomKills", 0) > 0:
            pressure.append(a["name"])
        elif max(g.get("memPsiPct", 0), g.get("cpuPsiPct", 0), g.get("ioPsiPct", 0)) >= 1 and level == "Чисто":
            level = "Тисне"
    if pressure:
        level, service = "Назріває", service or pressure[0]
    info["pressure"] = pressure

    # trust in the forecast: downgrade when the agent is wrong more often than right
    if level == "Назріває" and best >= 0.7 and not pressure and hits + misses >= 10 and precision is not None and precision < 60:
        level = "Тисне"
        info["downgraded"] = True
    info["service"] = service
    tier1 = service in nodes and nodes[service]["tier"] == 1
    info["actNow"] = bool(level == "Назріває" and tier1 and lead_ms is not None and lead_ms < 30 * 60000
                          and not info.get("downgraded"))
    return level, info


# ------------------------------------------------------------ indicator 5 ---

def day(d: dict) -> tuple[str, dict]:
    tenant = d["status"]["tenantStats"]["tenants"][d["tenant"]]
    hist = tenant.get("signalsHistory", [])
    if len(hist) < MIN_BUCKETS:
        return "—", {"why": f"only {len(hist)} buckets"}
    recent, base = hist[-RECENT_BUCKETS:], hist[:-RECENT_BUCKETS]
    r_req, r_err = sum(b["requests"] for b in recent), sum(b["requestErrors"] for b in recent)
    b_req, b_err = sum(b["requests"] for b in base), sum(b["requestErrors"] for b in base)
    if b_req < 1000:
        return "—", {"why": "base window too small"}
    err_recent, err_base = 100 * r_err / r_req, 100 * b_err / b_req
    peak = max((100 * b["requestErrors"] / b["requests"]) for b in hist if b["requests"])

    now = parse(d["now"])
    start_of_day = now.replace(hour=0, minute=0, second=0)
    today = sum(1 for i in d["incidents"]["incidents"] if parse(i["firstSeen"]) >= start_of_day)
    weeks = {}
    for b in d["analytics"]["baselines"]:
        for w, n in b.get("weeklyIncidentCounts", {}).items():
            weeks[w] = weeks.get(w, 0) + n
    weekly_median = statistics.median(weeks.values()) if weeks else 0
    per_day = weekly_median / 7
    repeat = tenant.get("repeatRatePct", 0) if tenant.get("sampledIncidents") else 0
    info = {"errRecent": round(err_recent, 2), "errBase": round(err_base, 2), "peakBucket": round(peak, 2),
            "incidentsToday": today, "normPerDay": round(per_day, 2), "repeatRate": repeat}

    if (err_recent > 2 * err_base and err_recent >= DAY_FLOOR_PCT) or repeat > 20 or today > 2 * per_day:
        return "Погіршилась", info
    open_now = tenant.get("incidents", {}).get("openNow", 0)
    if peak > 3 * err_base and err_recent <= 1.5 * err_base and open_now == 0:
        return "Осіла", info
    return "Спокійна", info


# ------------------------------------------------------------ indicator 1 ---

def verdict(d: dict) -> dict:
    t, ti = trust(d)
    if t == "Наосліп":
        return {"verdict": "НАОСЛІП", "states": {"users": "—", "forecast": "—", "trust": t, "day": "—"},
                "detail": {"trust": ti}}
    u, ui = users(d)
    f, fi = forecast(d)
    y, yi = day(d)
    crit = d["incidents"]["incidentMetrics"].get("criticalOpen", 0)
    warn = d["incidents"]["incidentMetrics"].get("warningOpen", 0)
    if u == "Зламано" or crit > 0:
        v = "ЗАРАЗ"
    elif f == "Назріває" and fi.get("actNow"):
        v = "ЗАРАЗ"
    elif u == "Страждають" and ui.get("escalate"):
        v = "ЗАРАЗ"
    elif u == "Страждають" or f == "Назріває" or y == "Погіршилась" or warn > 0 or t == "Частково":
        v = "ЗАПЛАНУВАТИ"
    else:
        v = "СПОКІЙНО"
    return {"verdict": v, "states": {"users": u, "forecast": f, "trust": t, "day": y},
            "detail": {"users": ui, "forecast": fi, "trust": ti, "day": yi, "criticalOpen": crit, "warningOpen": warn}}


def main(argv: list[str]) -> int:
    only = argv[1] if len(argv) > 1 else None
    files = sorted(HERE.glob("s*.json"))
    failed = 0
    print(f"{'scenario':<26}{'users':<12}{'forecast':<12}{'trust':<12}{'day':<14}{'verdict':<14}ok")
    for path in files:
        if only and not path.name.startswith(only):
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        got = verdict(d)
        exp = d["expected"]
        ok = got["verdict"] == exp["verdict"] and got["states"] == exp["states"]
        failed += 0 if ok else 1
        s = got["states"]
        print(f"{d['scenario']:<26}{s['users']:<12}{s['forecast']:<12}{s['trust']:<12}{s['day']:<14}{got['verdict']:<14}{'✓' if ok else '✗ expected ' + exp['verdict'] + ' ' + str(exp['states'])}")
        if only:
            print(json.dumps(got["detail"], ensure_ascii=False, indent=2))
    print(f"\n{len(files) - failed}/{len(files)} scenarios match metrics_spec.md" if not only else "")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
