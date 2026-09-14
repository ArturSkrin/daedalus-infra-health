# Metrics catalog for the Triage Vitals mobile screen

**Status:** Reference, 2026-09-14.

A list of the numbers the Triage core already publishes over its HTTP API, and
which of them suit the mobile Vitals screen. Written for someone who has not
worked on this codebase.

Sources: the OpenAPI document the core serves.

## Background

Triage watches Kubernetes clusters for one or more **tenants** (a customer or a
team). It reads a stream of **events**, classifies each one as noise, signal or
incident, and opens an **incident** when something needs attention. A tenant has
a **service graph**, the list of its services and who calls whom. Most API
responses can be narrowed to one tenant with a `?tenant=` query parameter.

## What Triage collects

| Class | Arrives as | Numbers | Event raised |
| --- | --- | --- | --- |
| Kubernetes events | Event informer, or cluster agent | none | the Warning reason |
| Application readiness | Application CR transitions | ready, components ready | `AppDegraded`, `AppRecovered`, `AppStatusChanged` |
| Log metrics | agent `log_metrics` | `errorCount`, `warnCount`, `totalCount`, sample line | `LogErrorAnomaly` above 0 errors or warns |
| RED anomalies | agent `red_metrics` | `requestCount`, `errorCount`, `p99Ms`, failing route | `RequestErrorAnomaly` above 0 errors |
| RED summary | agent `red_summary`, every window | `requestCount`, `errorCount`, `p99Ms` | none |
| USE anomalies | agent `use_metrics` | `cpuPsiAvg60`, `memPsiAvg60`, `ioPsiAvg60`, `cpuPct`, `memPct`, `oomKills`, `throttledPct`, worst pod | `ResourcePressureAnomaly` at PSI 1%, any OOM kill, or `memPct` 50% |
| USE summary | agent `use_summary`, every window | PSI, `oomKills`, `memPct`, `cpuPct`, same against node capacity and pod requests, plus denominators | none |
| Graph drift | agent `topology_snapshot`, ~10 min | observed workloads and calls | `GraphDrift` on a difference from the declared graph |
| External providers | `POST /events/<provider>/`, Bearer | `type`, `message`, `severity`, `source`, `raw` | one event of that `type` |
| Human | chat webhook, MCP `emit_event`, A2A | text | one event, guardrailed |

The cluster agent runs in each watched cluster and streams to the core over an
outbound WebSocket.

PSI is Linux Pressure Stall Information: time spent stalled waiting for CPU,
memory or disk. Utilisation and PSI move independently.

Security findings use the external-provider path: a scanner or CNAPP posts a
finding, it resolves to a service through the service graph, and it can open an
incident. Findings land in the event mix and the incident counts. No API field
marks them as security.

`LogErrorAnomaly`, `RequestErrorAnomaly`, `ResourcePressureAnomaly` and
`GraphDrift` never open an incident. `AppDegraded` does.

## Where the numbers live

| Endpoint | What it returns | Size |
| --- | --- | --- |
| `GET /v2/agent/status` | Everything about the running core, plus a per-tenant block under `tenantStats.tenants` | 330 fields |
| `GET /v2/agent/incidents?tenant=` | The incident list plus summary counts and averages | 13 fields plus one record per incident |
| `GET /v2/agent/applications?tenant=` | Per-application CPU, memory, traffic, errors, readiness | One record per app instance |
| `GET /v2/agent/graph?tenant=` | Service graph nodes and edges | One record per node and edge |
| `GET /v2/agent/analytics?tenant=` | Weekly history and per-service averages | One record per service |
| `GET /v2/memory/metrics?tenant=` | Counters for the memory subsystem | 47 fields |

## Two rules that apply to every metric

**Check the tenant.** `/v2/agent/status` has no `?tenant=` parameter. Only the
block at `tenantStats.tenants[<name>]` belongs to one tenant. Everything else in
that response covers the whole core, including `worldState`, `queue` and
`classifierStats`. Read the tenant you asked for by name, and show nothing if it
is missing. Do not fall back to another tenant.

**Zero is not always zero.** Most counters are omitted from the JSON when the
core has nothing to report. A missing value means "not measured", and should
render as a dash rather than as 0 or as a met goal. Each metric below names the
field to check first.

## Metrics suited to the Vitals screen

All of these come from `tenantStats.tenants[<name>]` on `/v2/agent/status`
unless the Where column says otherwise.

| Metric | Field | Unit | Better | Show nothing when | Suggested use |
| --- | --- | --- | --- | --- | --- |
| Event mix | `events.noise`, `.signal`, `.incident`, `.unknown`, `.drift` | Counts | n/a | All five are 0 | Zone bar |
| Signal share | `snrPct` | 0-100 | Higher | Missing | Ring |
| Service coverage | `serviceCoveragePct` | 0-100 | Higher | `services` is 0 | Ring |
| Services not reporting | `servicesDark` | Count | Lower | `services` is 0 | Tile |
| Time to recover | `mttrMs` | Milliseconds | Lower | Missing | Ring |
| Time to detect | `mttdMs` | Milliseconds | Lower | Missing | Tile |
| Resolution rate | `resolutionRatePct` | 0-100 | Higher | Missing | Ring |
| Prediction accuracy | `predictionPrecisionPct` | 0-100 | Higher | `predictionHits + predictionMisses` is 0 | Ring |
| Warning time | `predictionAvgLeadMs` | Milliseconds | Higher | `predictionHits` is 0 | Ring |
| Events per incident | `eventsPerIncident` | Ratio | Higher | Missing | Tile |
| Repeat incidents | `repeatRatePct` | 0-100 | Lower | `sampledIncidents` is 0 | Tile |
| Auto-resolved | `autoResolvedPct` | 0-100 | Higher | `sampledIncidents` is 0 | Tile |
| Predicted in advance | `precursorCoveragePct` | 0-100 | Higher | `sampledIncidents` is 0 | Tile |
| Signal families | `signalsByType` | Four counts | n/a | Map absent | Tile |
| Last 24 hours | `signalsHistory` | 5-minute buckets | n/a | Array absent | Sparkline |
| Open incidents | `incidents.openNow` | Count | Lower | Never, 0 is real | Tile |
| Open by severity | `incidentMetrics.criticalOpen`, `.warningOpen`, `.infoOpen`. Where: `/v2/agent/incidents?tenant=` | Counts | Lower | Never, 0 is real | Tile |
| Median recovery | `incidentMetrics.medianTTR`. Where: `/v2/agent/incidents?tenant=` | Seconds | Lower | 0 | Tile |
| Oldest open incident | Derived from `incidents[].firstSeen`. Where: `/v2/agent/incidents?tenant=` | Seconds | Lower | No open incident | Ring input |
| Apps ready | `ready` and `componentsReady`. Where: `/v2/agent/applications?tenant=` | Counts | Higher | `observedAt` is absent | Tile |
| Incidents per week | `baselines[].weeklyIncidentCounts`. Where: `/v2/agent/analytics?tenant=` | Counts per week | Lower | Map empty | Weekly bars |

### Metrics formulas

1. `snrPct` and the core-wide `classifierStats` compute the signal share
   differently. The per-tenant counters are exclusive, so the per-tenant value
   is `(signal + incident) / (signal + incident + noise)`. The core-wide
   counters count incidents inside signal, so that value is
   `signal / (signal + noise)`. If a client falls back from one to the other it
   must subtract incident out.
2. `mttdMs` measures how long detection took. It is not warning time and it
   moves the opposite way. Use `predictionAvgLeadMs` for a warning-time ring.
3. `mttrMs`, `mttdMs`, `resolutionRatePct` and `incidents.openNow` are sampled
   from incidents held in memory. They reset when the core restarts, so a ring
   can move without anything changing in the cluster.

## Metrics recommended for screens

| Area | Fields | Endpoint |
| --- | --- | --- |
| Per-service traffic, errors, latency | `golden.reqPerSec`, `golden.errPct`, `golden.p99Ms`, valid only when `golden.rateAsOfUnix` is set | `/v2/agent/applications` |
| Per-service pressure | `golden.cpuPsiPct`, `golden.memPsiPct`, `golden.ioPsiPct`, `golden.oomKills`, valid only when `golden.saturationAsOfUnix` is set | `/v2/agent/applications` |
| Per-service usage | `golden.memPct`, `golden.cpuPct`, `golden.memNodePct`, `golden.cpuNodePct`, `golden.memReqPct`, `golden.cpuReqPct` and their byte and core denominators, valid only when `golden.utilizationAsOfUnix` is set | `/v2/agent/applications` |
| Service importance and dependencies | `nodes[].blastRadius` (0-1), `nodes[].weight`, `nodes[].tier`, `nodes[].calls`, `nodes[].calledBy`, `edges[]` | `/v2/agent/graph` |
| Per-service averages | `baselines[].mttrMean`, `.mttdMean`, `.blastRadiusMean`, `.reopenRate`, `.incidentRateWeek` | `/v2/agent/analytics` |
| Recurring patterns and early matches | `patterns[]`, `precursorMatches[].confidence`, `.matchedSteps`, `.totalSteps` | `/v2/agent/analytics` |
| Incident content | `incidents[].rca`, `.investigationPlan`, `.relatedEvents`, `.reopenCount` | `/v2/agent/incidents` |
| Unmapped services | `knownServices`, `unmappedServices`, `unmappedNames`, `unmappedTruncated` | `/v2/agent/status` |
| LLM cost | `llmTokens`, `llmCalls`, `llmTokenRatio`, `llmRatioToday`, `llmRatio7d`, and `llmBudget.byTenant` | `/v2/agent/status` |
| Ownership | `ownership.resolved`, `.unattributed`, `.contested`, `.teams` | `/v2/agent/status` |
| Cluster connections | `gossip`, `clusterAgentStats`, `retention` | `/v2/agent/status` |

## Collected, no per-tenant field

Each needs a core change before a per-tenant screen can show it.

| What | Today | Missing |
| --- | --- | --- |
| Rate, error rate, p99 | per application; summed into `signalsHistory[].requests` and `.requestErrors` for 24h | tenant-wide rate, error percentage, latency |
| CPU and memory pressure | per application | tenant-wide figure; count of services under pressure |
| CPU throttling | `throttledPct` in a `ResourcePressureAnomaly` `raw` only | never stored per service |
| Log volume | `warnCount`, `totalCount` in a `LogErrorAnomaly` `raw` only | never stored per service |
| Anomaly samples | in each event `message` and `raw` | absent from every summary |
| Security findings | ordinary events with a provider `source` | no counter |
| Pods over request | `memReqPct`, `cpuReqPct` per application | no count of services over |
| Graph drift | `GraphDrift` events, `events.drift` lifetime count | no list of drifted services |
