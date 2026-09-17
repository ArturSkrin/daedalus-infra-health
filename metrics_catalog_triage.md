# Triage metrics catalog review

Source: [reference/vitals-metrics-catalog.md](reference/vitals-metrics-catalog.md) (Reference, 2026-09-14), the catalog from the organizers. Each metric from the catalog is sorted into one of three categories:

- **Changes the decision**: without it, one of the three decisions (intervene / schedule / nothing) would be different.
- **Explains the decision**: shows why the agent decided this way. Belongs in the drill-in.
- **Changes nothing**: an interesting number, but no decision depends on it.

All fields are from `tenantStats.tenants[<name>]` on `GET /v2/agent/status`, unless stated otherwise.

## 1. Changes the decision

| Field | Endpoint | Which decision it changes | Threshold (draft) | Comment |
| --- | --- | --- | --- | --- |
| `incidentMetrics.criticalOpen` | `/v2/agent/incidents` | intervene now | > 0 | The only field that gives "now" on its own. 0 here is a real zero. |
| `incidentMetrics.warningOpen` | `/v2/agent/incidents` | schedule | > 0 | Open, but not critical. |
| `incidents.openNow` | status | now / schedule | > 0 | Duplicates the previous two, needed only as a consistency check. |
| `golden.reqPerSec`, `golden.errPct`, `golden.p99Ms` | `/v2/agent/applications` | intervene now | errPct, weighted by blastRadius | Valid only if `golden.rateAsOfUnix` is fresh. There is no tenant-wide value, we compute it ourselves. |
| `nodes[].blastRadius`, `nodes[].tier` | `/v2/agent/graph` | now or schedule | tier 1 or blastRadius >= 0.5 raises a warning to "now" | This is a weight, not an indicator. On screen it is not a number, but "will hit N services, including X". |
| `precursorMatches[].confidence`, `.matchedSteps`, `.totalSteps` | `/v2/agent/analytics` | schedule (future) | confidence >= 0.7 and matchedSteps/totalSteps >= 0.5 | The only real forecast in the catalog. This is our indicator into the future. |
| `golden.memPsiPct`, `golden.cpuPsiPct`, `golden.ioPsiPct`, `golden.oomKills` | `/v2/agent/applications` | schedule | PSI >= 1% or oomKills > 0 | Valid only with `golden.saturationAsOfUnix`. This is the "nearest future" from resource physics. |
| `golden.memReqPct`, `golden.memPct` | `/v2/agent/applications` | schedule | memReqPct >= 90% with PSI > 0 | Together with PSI gives "memory is saturating". |
| `repeatRatePct` | status | schedule | > 20% | The problem keeps coming back, so it needs work on the root cause, not firefighting. Show only when `sampledIncidents` > 0. |
| `serviceCoveragePct`, `servicesDark` | status | **blocks all decisions** | coverage < 90% or dark > 0 | Trust in the data. If it is low, the decision is "fix collection first". |
| `clusterAgentStats`, `gossip` | status | **blocks all decisions** | the cluster agent is not connected | No stream, no tracker. |
| `golden.*AsOfUnix` | `/v2/agent/applications` | **blocks the indicator** | older than 2 windows | Freshness of each golden block separately. |
| `predictionPrecisionPct` | status | trust in the forecast | < 60%: we show the forecast in gray | Show only when `predictionHits + predictionMisses` > 0. |
| `ready`, `componentsReady` | `/v2/agent/applications` | intervene now | ready = false in tier 1 | Almost always already open as an incident through `AppDegraded`, so this is a safety net. |

## 2. Explains a decision already made

| Field | Endpoint | What it explains |
| --- | --- | --- |
| `events.noise/signal/incident/unknown/drift` | status | How much noise the agent absorbed instead of us. An argument for trust, not a decision. |
| `snrPct` | status | The same as a single number. In the drill-in "trust in the agent". |
| `signalsByType` | status | Which signal family dominates (log / red / use / k8s). Attribution. |
| `signalsHistory` | status | The texture of the day. A sparkline in the drill-in, and also the source for "how the day went" through `.requests` and `.requestErrors`. |
| `autoResolvedPct` | status | Why "do nothing" is safe: the agent closed N% on its own. |
| `precursorCoveragePct` | status | How many incidents the agent predicted in advance. Explains trust in the forecast. |
| `predictionAvgLeadMs` | status | How much time there usually is after a warning. The horizon for "schedule". |
| `mttrMs`, `mttdMs`, `incidentMetrics.medianTTR` | status, incidents | Goals, not decisions. They reset on a core restart, so they are dangerous on the main screen. |
| oldest open incident (`incidents[].firstSeen`) | incidents | The order in the queue, not the decision itself. |
| `incidents[].rca`, `.investigationPlan`, `.relatedEvents`, `.reopenCount` | incidents | The content of the drill-in for an open incident. |
| `baselines[].mttrMean`, `.mttdMean`, `.blastRadiusMean`, `.reopenRate`, `.incidentRateWeek` | analytics | The norm for a service. Needed to say "worse than usual". |
| `patterns[]` | analytics | Which exact pattern matched. The forecast drill-in. |
| `ownership.resolved/unattributed/contested` | status | Who has to respond. Changes the addressee, not the decision. |
| `golden.memNodePct`, `cpuNodePct`, denominators | applications | Explanation of saturation in the drill-in. |
| `knownServices`, `unmappedServices`, `unmappedNames` | status | Explanation of low trust: which services are not in the graph. |
| `baselines[].weeklyIncidentCounts` | analytics | The weekly trend for a quiet day. |

## 3. Changes nothing

| Field | Why |
| --- | --- |
| `resolutionRatePct` | The share of closed incidents. A retrospective, no decision depends on it. |
| `eventsPerIncident` | A measure of classifier quality, not of fleet state. |
| `llmTokens`, `llmCalls`, `llmTokenRatio`, `llmRatioToday`, `llmRatio7d`, `llmBudget.byTenant` | The cost of the agent itself, not of the infrastructure. This is not the "cost anomaly" from the brief. |
| `retention` | A setting, not a state. |
| `nodes[].weight`, `nodes[].calls`, `.calledBy`, `edges[]` | Needed to compute blastRadius, not read on their own. |
| `incidentMetrics.infoOpen` | Info incidents lead to no decision. |

## 4. Five indicators of the main screen (updated draft)

| # | Indicator (as the engineer reads it) | Decision | From which fields | Trust |
| --- | --- | --- | --- | --- |
| 1 | **Fleet state in one word**: ALL CLEAR / SCHEDULE / ACT NOW | all three | criticalOpen gives ACT NOW; warningOpen, precursor >= 0.7, PSI >= 1%, repeatRate > 20% give SCHEDULE; otherwise ALL CLEAR | grayed out if #4 is red |
| 2 | **Users now**: "all requests are going through" / "X% of traffic is failing in N services" | now | sum of errPct x reqPerSec x blastRadius over apps with a fresh rateAsOfUnix, plus criticalOpen | freshness of rateAsOfUnix |
| 3 | **What's brewing** (future): "agent sees 3 of 5 steps to a payments failure, usually ~40 min of warning" / "nothing is brewing" | schedule | precursorMatches, predictionAvgLeadMs, PSI + memReqPct | predictionPrecisionPct |
| 4 | **Can we trust it**: "we see 11 of 12 services, data is 40 s old" | blocks the rest | serviceCoveragePct, servicesDark, clusterAgentStats, unmappedServices, *AsOfUnix | is trust itself |
| 5 | **How the day went**: "the agent closed 7 on its own, 0 came back, errors as usual" | nothing / schedule | signalsHistory.requests and .requestErrors against baselines, autoResolvedPct, repeatRatePct, incidentRateWeek | sampledIncidents > 0 |

## 5. Gaps found (for the nomination)

1. **No release or deploy event.** The brief says the tracker is opened "to understand how the release went", but the API has no rollout marker at all. The closest: `GraphDrift` and `AppStatusChanged`. Indicator #5 has to be built as "the day", not "the release". Needed: a `Deploy` event with a time and a service.
2. **No USE history.** PSI and memPct exist only as a current snapshot on `/v2/agent/applications`. "Memory has been saturating for three days" cannot be computed from the API, a time series is needed. `signalsHistory` has 5-minute buckets only for signals and requests.
3. **Security is invisible.** The brief names security breaches as one of the three goals, and the catalog says directly: no field marks a security event. Needed: a filter by `source` or a counter in `signalsByType`.
4. **No tenant-wide RED.** The catalog admits it: rate, error%, p99 exist only per app. Indicator #2 is computed by the client, and the weighting formula is ours, not the agent's.
5. **Infrastructure cost is absent.** The only cost in the catalog is the LLM tokens of the agent itself. The "cost anomalies" from the brief are not represented in the API.
6. **Retrospective goals reset on restart.** `mttrMs`, `mttdMs`, `resolutionRatePct`, `openNow` live in core memory. The ring can move with no changes in the cluster. An argument against putting them on the main screen.

## 6. Arguments against indicators the organizers treat as primary

- **"% of goals" in the center of the screen.** The reference screen shows "100% of goals" next to a DEGRADED state and an open critical incident. Goals (awareness, warning, recovery) are metrics of agent quality, not of fleet state, so they can be 100% met at the very moment you need to run. The center of the screen must be taken by the decision.
- **SNR / Signal share as a vital.** `snrPct` explains how much noise was filtered out, but none of the three decisions depends on it. It belongs in the drill-in as evidence of trust in the agent.
- **A raw event counter in the "crown"** (use 99, red 0, log 8 913, k8s 159 481). The brief explicitly forbids raw values on the main screen; the catalog itself calls this "raw feed, not a vital".
- **Five tabs** (Trends, Apps, Vitals, Cost, Secure) against a limit of "four maximum", while Cost and Secure have no fields in the API.
