# metrics_spec.md: five indicators of the main screen

Each indicator is described with the same scheme: what the engineer sees, which decision it changes, the threshold, which API fields it is computed from, the horizon, the trust indicator. Fields come from the Triage catalog ([reference/vitals-metrics-catalog.md](reference/vitals-metrics-catalog.md), 2026-09-14). All per-tenant fields are read from `tenantStats.tenants[<tenant>]` on `GET /v2/agent/status`, unless stated otherwise.

The rules below are implemented once, in `backend/engine.py`. Every number in this document is a named constant in `backend/thresholds.py`, and the "How this indicator decides" text on screen is generated from those constants. Raw API responses are read in one place, `backend/bundle.py`, which turns a missing or malformed field into an explicit "not measured" instead of a zero or a crash. The rules are checked by `tests/`: every scenario, both sides of every threshold, and 35 kinds of incomplete input. State codes in the code map to the words here as listed in `mock_data/README.md`.

Three decisions the screen has to suggest:

| Decision | Word on screen | What the engineer does |
| --- | --- | --- |
| intervene now | **ACT NOW** | opens the incident, acts today |
| schedule work | **SCHEDULE** | creates a ticket for the sprint, not today |
| do nothing | **ALL CLEAR** | closes the app |

Plus a fourth, service state **BLIND**: the data cannot be trusted, and the only action is to fix collection. It is not a fourth decision, it is the absence of grounds for any of the three.

## Shared rules

- **A missing field renders as a dash, not as 0.** Catalog: "Zero is not always zero". Each indicator below names the field that is checked first. This applies to decisions as well as to rendering: an indicator that cannot be measured is in the state "—" (unknown), never in its green state.
- **Freshness.** Each `golden.*` block on `/v2/agent/applications` has its own `*AsOfUnix`. A block is fresh if `now - asOfUnix <= 300 s` (5 agent windows of 60 s). A stale block is excluded from the formulas, not read as zero.
- **Tenant.** We show only `tenantStats.tenants[<tenant>]`. If the block is missing, indicator 4 goes to BLIND, and the others are not rendered.
- **Service weights.** `blastRadius` and `tier` come from `/v2/agent/graph` `nodes[]`. Tier 1 means a service on the user path. These numbers are not shown on screen, they are only a weight.
- **Raw values do not reach the main screen.** Errors, PSI, p99 live in the drill-in.

---

## 1. Fleet state

**What the engineer sees.** One word in the center: ALL CLEAR / SCHEDULE / ACT NOW / BLIND. Below it, one reason line generated from the indicator that produced the word: "checkout: 6% of requests are failing" or "all good, the agent closed 3 on its own".

**Decision.** This is the decision. The indicator measures nothing itself, it rolls up indicators 2–5 by priority rules.

**Roll-up rule (the first one that fires wins).**

| # | Condition | Word |
| --- | --- | --- |
| 1 | indicator 4 = Blind | BLIND |
| 2 | indicator 2 = Broken, or `incidentMetrics.criticalOpen > 0` | ACT NOW |
| 3 | indicator 3 = Brewing and lead < 30 min and the service is tier 1 | ACT NOW |
| 4 | indicator 2 = Degraded, or indicator 3 = Brewing, or indicator 5 = Regressed, or `incidentMetrics.warningOpen > 0`, or indicator 4 = Partial | SCHEDULE |
| 5 | none of the above, but one of indicators 2, 3, 5 could not be judged | ALL CLEAR, dimmed, and the reason line says what is missing |
| 6 | otherwise | ALL CLEAR |

**Why rule 5 is not SCHEDULE.** An indicator is unknown for one of two reasons. Either collection is broken, and then indicator 4 is already Partial and rule 4 gives SCHEDULE, because a human can fix collection. Or the data simply does not exist yet, as with the 24 h history after a core restart, and then there is nothing to put in a ticket: it heals by itself. A SCHEDULE with no work behind it would teach the engineer to ignore the word. So the decision stays "do nothing", and the screen is honest about the missing part (scenario S11).

**Why this way.** A plain ALL CLEAR is reachable only when all four indicators are green. This is the requirement "there must be a state that means nothing needs to be done": it is defined through the absence of grounds, not through a separate metric.

**API fields.** `incidentMetrics.criticalOpen`, `incidentMetrics.warningOpen` from `GET /v2/agent/incidents?tenant=`. The rest through indicators 2–5.

**Horizon.** Inherited from the indicator that fired: now (2), hours (3), day (5).

**Trust.** The word dims if indicator 4 = Partial, and is replaced with BLIND if indicator 4 = Blind.

**Drill-in.** The list of rules above with the one that fired highlighted. This is the only place where the engineer sees the logic.

---

## 2. Users now

**What the engineer sees.** A ring and a caption: "all requests are going through" / "1.2% of requests are failing in 2 services" / "checkout is down". This is the impact on a person right now, RED as a state.

**Decision.**

| State | Condition | Decision |
| --- | --- | --- |
| Fine | `failingShare < 0.5%` and no tier-1 service has `errPct >= 1%` | nothing |
| Degraded | `0.5% <= failingShare < 5%`, or any tier-1 service has `1% <= errPct < 5%` | schedule; **now**, if the largest `blastRadius` among the affected services is >= 0.5 (in practice: the affected service is on the user path) |
| Broken | `failingShare >= 5%`, or any tier-1 service has `errPct >= 5%`, or a tier-1 service has `ready = false` (readiness counts even when the traffic data of that service is stale) | now |

**Formula.** Over all records of `GET /v2/agent/applications?tenant=` with a fresh `golden.rateAsOfUnix`:

```
failingShare = Σ(reqPerSec_i × errPct_i / 100) / Σ(reqPerSec_i)
affected     = { i : errPct_i >= 1% }
blastMax     = max blastRadius_i for i in affected   (from /v2/agent/graph)
```

There is no tenant-wide RED in the API (catalog, section "Collected, no per-tenant field"), so the formula is ours. It weights errors by traffic, so that 50% errors in a service with 0.1 rps do not raise an alarm.

We take the maximum, not the sum of blastRadius: the values of neighboring services overlap across the graph, and the sum of two tier-2 services (0.31 + 0.34) would fake the importance of one tier-1 service. The first version used the sum, and because of it scenario S03 gave ACT NOW instead of SCHEDULE.

**Fields.** `golden.reqPerSec`, `golden.errPct`, `golden.rateAsOfUnix`, `ready`, `observedAt` (`/v2/agent/applications`); `nodes[].blastRadius`, `nodes[].tier` (`/v2/agent/graph`); `incidentMetrics.criticalOpen` (`/v2/agent/incidents`).

**Deliberately not used.** `golden.p99Ms` is shown only in the drill-in. The API has no per-service p99 baseline (`baselines[]` has mttr, mttd, blastRadius, reopenRate, incidentRate, but no latency), so a threshold for p99 cannot be formulated, and an indicator without a threshold is just a number.

**Horizon.** The present: the last agent window.

**Trust.** The share of traffic with a fresh `rateAsOfUnix`: `freshShare = Σ reqPerSec(fresh) / Σ reqPerSec(all)`. If `freshShare < 90%`, the ring is gray with the caption "we see N of M services". If `Σ reqPerSec = 0` or no record has `rateAsOfUnix`, a dash.

**Drill-in.** The list of affected services, for each: errPct, reqPerSec, p99Ms, blastRadius, `calledBy` (who gets hit next), the open incident with `rca` and `investigationPlan`.

---

## 3. What's brewing

**What the engineer sees.** A ring and a caption: "nothing is brewing" / "memory pressure in catalog, there is time" / "agent sees 3 of 5 steps to a payments failure, usually ~40 min of warning". This is the only indicator with a horizon in the future.

**Decision.**

| State | Condition | Decision |
| --- | --- | --- |
| — | no service has fresh resource-pressure data and there is no pattern match: "nothing is brewing" would be a guess | none from this indicator; indicator 4 goes Partial |
| Clear | no matches and no pressure, with fresh resource data to back it | nothing |
| Pressure | a precursor with `0.5 <= confidence < 0.7`, or `PSI >= 1%` with no other signs | nothing, a mention in the drill-in |
| Brewing | a precursor with `confidence >= 0.7` and `matchedSteps/totalSteps >= 0.5`; or `memPsiPct >= 1%` and `memReqPct >= 90%` in the same service; or `oomKills > 0` in a fresh window; or any resource stall (CPU, memory, disk PSI) `>= 10%` in one service | schedule; **now**, if the service is tier 1 and `lead < 30 min` and the agent has at least 10 past predictions |

`lead` equals the tenant's `predictionAvgLeadMs`. If `predictionHits = 0`, the lead is unknown and the "now" rule does not fire: the indicator gives only "schedule". The same holds while `predictionHits + predictionMisses < 10`: one lucky prediction is 100% precision, and "usually N min of warning" from a handful of cases is not a usual anything. An agent with a short track record can ask for a ticket, not for a person right now.

**Why a 10% stall counts on its own.** Memory has a cliff, the OOM kill, so it gets the early rule (1% stall at 90% of the request). CPU and disk have no cliff, but a service stalled a tenth of the time is already failing slowly. `ResourcePressureAnomaly` never opens an incident (catalog), so if this indicator stays silent, nobody says it.

**Formula.** Two independent sources, either of them raises the state:

```
precursorLevel = max over precursorMatches[] of
                 (confidence if matchedSteps/totalSteps >= 0.5 else confidence × 0.5)
pressureLevel  = any app with fresh saturationAsOfUnix where
                 memPsiPct >= 1 and memReqPct >= 90, or oomKills > 0
```

**Fields.** `precursorMatches[].confidence`, `.matchedSteps`, `.totalSteps`, `.service`, `patterns[]` (`/v2/agent/analytics?tenant=`); `predictionAvgLeadMs`, `predictionHits`, `predictionMisses`, `predictionPrecisionPct` (status); `golden.memPsiPct`, `golden.cpuPsiPct`, `golden.ioPsiPct`, `golden.oomKills`, `golden.memReqPct`, `golden.saturationAsOfUnix`, `golden.utilizationAsOfUnix` (`/v2/agent/applications`).

**Horizon.** For a precursor: `predictionAvgLeadMs` (from minutes to hours). For PSI: the next hours, without an exact figure, because the API has no USE history (see gaps).

**Trust.** `predictionPrecisionPct` when `predictionHits + predictionMisses >= 10`. If `< 60%`, the caption is "the agent is often wrong", the state drops by one level (Brewing becomes Pressure) and "now" does not fire. If there are no matches, trust is not shown. For PSI, trust equals the freshness of `saturationAsOfUnix`.

**Drill-in.** The matched pattern: name, steps already passed, steps remaining, past incidents of this pattern. For pressure: the service, PSI for the three resources, memReqPct, memNodePct.

---

## 4. Can we trust it

**What the engineer sees.** A ring and a caption: "we see all 12 services, data is 40 s old" / "3 services are silent" / "cluster agent is not connected". This is the answer to "do zero events mean health or missing data".

**Decision.**

| State | Condition | Consequence for the rest of the screen |
| --- | --- | --- |
| Full | the agent is connected, `serviceCoveragePct >= 95`, `servicesDark = 0`, `unmappedServices = 0`, `freshShare >= 90%` | the other indicators as is |
| Partial | the agent is connected and (`80 <= coverage < 95`, or `1 <= servicesDark <= 2`, or `unmappedServices > 0`, or `freshShare < 90%`, or fewer than 90% of services have fresh resource-pressure data, or `events.unknown` is 20% or more of all classified events) | indicator 1 cannot give ALL CLEAR, SCHEDULE at minimum; the reason line must name the services explicitly: "scheduler and backup silent for 6 h" |
| Blind | the tenant is missing from `tenantStats.tenants`, or the cluster agent is not connected, or the core does not report the agent link and no service has fresh data, or `coverage < 80`, or `servicesDark >= 3` | indicators 2, 3, 5 are gray; indicator 1 = BLIND |

**Why unclassified events are here and SNR is not.** The screen shows what the agent decided. If the agent could not classify a fifth of what it saw, its silence is not evidence of calm, and a human can look into why. `snrPct` looks like the same kind of signal, but it has no baseline in the API: in our fixture a quiet day is 0.7% (96 signals in 14 thousand noise events), so a "collapse" cannot be told apart from a normal noisy fleet. No baseline, no threshold, same reasoning as for p99.

**Why dark services lead to "schedule" and not "nothing".** A service that sends no events may be healthy or dead for collection. The API cannot tell the two apart, so this is work for today or tomorrow, but not a reason to close the app with an easy mind.

**Fields.** `serviceCoveragePct`, `services`, `servicesDark`, `knownServices`, `unmappedServices`, `unmappedNames`, `clusterAgentStats`, `gossip` (status); `golden.*AsOfUnix`, `observedAt` (`/v2/agent/applications`).

**Horizon.** The present.

**Trust.** The indicator is trust itself. Its only own "dash": `services = 0`, in which case coverage is meaningless and the state is Blind right away.

**Drill-in.** The list of dark and unmapped services by name, the time of the last event from each, agent connection state per cluster, the oldest `asOfUnix`.

---

## 5. How the day went

**What the engineer sees.** A ring and a caption: "quiet day, the agent closed 3 on its own" / "there was a spike at 09:40, it settled" / "three times more errors than normal over the last 2 h". This is the value on a quiet day: the engineer opens the tracker in the morning and after a release to see whether anything has changed.

**Decision.**

| State | Condition | Decision |
| --- | --- | --- |
| Quiet | `errRecent <= 2 × errBase`, `repeatRatePct <= 20`, `incidentsToday <= weeklyMedian / 7` | nothing |
| Settled | within the 24 h window there was a bucket with `errBucket > 3 × errBase`, but `errRecent <= errBase × 1.5`, and `incidents.openNow = 0` | nothing |
| Regressed | `errRecent > 2 × errBase` and `errRecent >= 0.3%`, or `repeatRatePct > 20`, or `incidentsToday > 2 × weeklyMedian / 7` | schedule |

The 0.3% floor protects against noise on low traffic. The first version had 0.5%, and scenario S03 (a release regressed to 0.46%) did not fall into any state. The `openNow = 0` condition for Settled appeared after scenario S07: without it the error curve said "settled" during an open critical incident. See `scenarios.md`.

**Formula.** From `signalsHistory[]` (5-minute buckets over 24 h, fields `.requests`, `.requestErrors`):

```
errRecent = Σ requestErrors / Σ requests    over the last 2 h (24 buckets)
errBase   = Σ requestErrors / Σ requests    over the preceding 22 h (264 buckets)
errBucket = requestErrors / requests        for each bucket
weeklyMedian = median of baselines[].weeklyIncidentCounts over the last 4 weeks, summed across services
```

A 2 h window instead of the initial 6 h: a regression after a release at 11:00, viewed at 13:10, was diluted by six hours down to 0.30% and did not cross the threshold. Two hours match how an engineer actually checks a release.

**Fields.** `signalsHistory[].requests`, `.requestErrors`, `autoResolvedPct`, `repeatRatePct`, `sampledIncidents`, `incidents.openNow` (status); `baselines[].weeklyIncidentCounts`, `baselines[].incidentRateWeek` (`/v2/agent/analytics`); `incidents[].firstSeen` for counting `incidentsToday` (`/v2/agent/incidents`).

**Horizon.** The past day with the trend into the current day. This is not a forecast, it is context for "do nothing".

**Trust.** `signalsHistory` must contain at least 230 of 288 buckets (80%). `repeatRatePct` and `autoResolvedPct` are shown only when `sampledIncidents > 0`. If `Σ requests` over the base window is < 1000, `errBase` is not computed and the state is limited to "Quiet" or a dash.

**The gap this indicator exposes.** The API has no deploy or release event. The indicator answers "how the day went", while the brief wants "how the release went". With a `Deploy{service, time}` marker, the `errRecent` / `errBase` windows would be split at the moment of the release, and the indicator would become more accurate. Recorded in `metrics_catalog_triage.md`, section 5.

**Drill-in.** A 24 h sparkline with the spike highlighted, the list of incidents for the day with the status "closed by agent" / "closed by human" / "open", `signalsByType` for spike attribution (log / red / use / k8s).

---

## Requirements check

| Requirement | How it is met |
| --- | --- |
| No more than 5 indicators | exactly 5, the incident queue is a list below them, not an indicator |
| At least one looks into the future | indicator 3 through `precursorMatches` and PSI |
| It is visible when the data cannot be trusted | indicator 4 plus a trust indicator in each of 2, 3, 5 |
| An "all is well" state exists | ALL CLEAR: indicator 2 Fine, 3 Clear, 4 Full, 5 Quiet or Settled, `warningOpen = 0` |
| No framework names and no raw values | words and shares on screen; errPct, PSI, p99, blastRadius only in the drill-in |
| USE, RED, SIG became a state, not sections | RED = indicator 2, USE = half of indicator 3, SIG = trust in 3 and 4 plus formulas that ignore a log spike without impact |
| A log errors spike without RED impact = do nothing | no indicator reads `signalsByType.log` or `LogErrorAnomaly`; the spike is visible only in the drill-in of indicator 5 |
| Silent services are not confused with healthy ones | `servicesDark` in indicator 4 leads to SCHEDULE, not to ALL CLEAR |
