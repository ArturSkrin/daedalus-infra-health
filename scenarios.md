# scenarios.md: running the five indicators through scenarios

Eleven scenarios instead of the minimum eight: the extra ones catch edge cases (an agent that is often wrong, a log spike with no impact, and a core with no history yet) where an indicator set breaks most often. Each scenario has the input values of the API fields, the state of each of the five indicators under the rules of `metrics_spec.md`, the expected decision, and what the run revealed.

Each scenario has a file in `mock_data/` with the same name.

## Shared fixture

Tenant `digital-purchases`, 12 services. Weights from `GET /v2/agent/graph`, traffic from `GET /v2/agent/applications`.

| Service | tier | blastRadius | reqPerSec (normal) |
| --- | --- | --- | --- |
| api-gateway | 1 | 0.71 | 420 |
| auth | 1 | 0.55 | 210 |
| checkout | 1 | 0.62 | 85 |
| payments | 1 | 0.58 | 60 |
| catalog | 2 | 0.31 | 300 |
| search | 2 | 0.28 | 150 |
| cart | 2 | 0.34 | 90 |
| notifications | 3 | 0.12 | 20 |
| image-resizer | 3 | 0.06 | 40 |
| reporting | 3 | 0.09 | 2 |
| scheduler | 3 | 0.05 | 0 (batch) |
| backup | 3 | 0.04 | 0 (batch) |

Total traffic is 1377 rps. The norm is `errBase = 0.20%`. Agent history: `predictionHits 31`, `predictionMisses 9`, `predictionPrecisionPct 78`, `predictionAvgLeadMs 2 460 000` (41 min). `serviceCoveragePct 100`, `servicesDark 0`, `unmappedServices 0`, the cluster agent is connected, all `*AsOfUnix` are no older than 60 s. `baselines[].weeklyIncidentCounts` over 4 weeks give a median of 4 incidents per week, that is `weeklyMedian / 7 = 0.57` per day. Anything a scenario does not override equals these values.

State notation: indicator 2 (Fine / Degraded / Broken), 3 (Clear / Pressure / Brewing), 4 (Full / Partial / Blind), 5 (Quiet / Settled / Regressed).

---

## S01. Quiet morning

`mock_data/s01_calm.json`

**Story.** Monday, 08:30. Nothing happened overnight. The engineer opens the tracker with a coffee.

**Input values.**

| Field | Value |
| --- | --- |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.errPct` across all services | 0.1–0.3 |
| `precursorMatches[]` | empty |
| `golden.memPsiPct` max | 0.2 (search) |
| `signalsHistory`: errRecent / errBase | 0.19% / 0.20% |
| `incidentsToday` | 0 |
| `events` over the day | noise 14 210, signal 96, incident 0 |

**States.** 2 Fine (failingShare 0.19%). 3 Clear. 4 Full. 5 Quiet.

**Expected decision: ALL CLEAR.** Reason line: "all normal, nothing happened in the last day".

**Check.** Passed. This proves that the "everything is fine" state is reachable, not theoretical.

**What it revealed.** The value on a quiet day rests on indicator 5: without it the screen would be just green, with no answer to "so what did the agent do". 14 thousand noise events were filtered out, and that is visible only in the drill-in, as it should be.

---

## S02. Release settled

`mock_data/s02_release_settled.json`

**Story.** At 09:35 checkout was rolled out. At 09:40 errors jumped, the agent opened an AppDegraded incident, at 09:52 the service recovered on its own, and the agent closed the incident. It is now 13:10.

**Input values.**

| Field | Value |
| --- | --- |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `signalsHistory`: buckets 09:40–09:50 | errBucket 1.4% (7 × errBase) |
| `signalsHistory`: errRecent (last 2 h) / errBase | 0.21% / 0.20% |
| `sampledIncidents / autoResolvedPct / repeatRatePct` | 1 / 100 / 0 |
| `incidentsToday` | 1 (the norm is 0.57 per day, less than 2 × the norm) |
| `golden.errPct` checkout now | 0.2 |

**States.** 2 Fine. 3 Clear. 4 Full. 5 Settled (there was a bucket > 3 × errBase, errRecent < 1.5 × errBase).

**Expected decision: ALL CLEAR.** Reason line: "09:40 spike settled, the agent closed it on its own".

**Check.** Passed. The engineer sees that the release was survived without them and does not dig into the logs.

**What it revealed.** The API has no deploy event. The tracker says "09:40 spike", not "09:35 release settled". The engineer links the spike to the release in their head. Gap 1 from `metrics_catalog_triage.md`.

---

## S03. Release regressed quietly

`mock_data/s03_release_regressed.json`

**Story.** At 11:00 catalog and cart were rolled out. Errors did not explode, but they have been steadily higher for two hours now. The agent did not open an incident, because no AppDegraded threshold was crossed. It is now 13:10.

**Input values.**

| Field | Value |
| --- | --- |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.errPct` catalog / cart | 1.0 / 1.5 |
| `golden.errPct` tier-1 services | 0.2 |
| failingShare | (300 × 1.0 + 90 × 1.5 + 987 × 0.2) / 1377 = 0.46% |
| `signalsHistory`: errRecent (2 h) / errBase | 0.46% / 0.20% |
| `sampledIncidents` | 0 |

**States.** 2 Fine (0.46% < 0.5%, tier-1 clean). 3 Clear. 4 Full. 5 Regressed (errRecent > 2 × errBase and >= 0.3%).

**Expected decision: SCHEDULE.** Reason line: "errors twice the norm since 11:00 in catalog and cart".

**Check.** Passed after four fixes, and this is the most productive scenario in the set.

1. The floor of the Regressed state was 0.5%, and 0.46% did not fall into any state. Lowered to 0.3%.
2. On paper the error share was calculated wrong (for 1.5% and 2.0% it equals 0.60%, not 0.46%), and `mock_data/evaluate.py` gave Degraded instead of Fine. The scenario values were lowered to 1.0% and 1.5%, and tier-1 was pinned at 0.2%.
3. The escalation in indicator 2 summed the blastRadius of the affected services: catalog 0.31 plus cart 0.34 gave 0.65 and ACT NOW. Replaced with the maximum, because the values of graph neighbors overlap.
4. The errRecent window was 6 h and blurred the two-hour regression down to 0.30%. Shortened to 2 h.

**What it revealed.** This is the main argument for indicator 5: indicator 2 looks at absolute impact and says "fine", and users really are almost fine. But relative to the norm it got twice as bad, and that is work for today. Without indicator 5 the regression would have been noticed a week later.

---

## S04. Memory is saturating

`mock_data/s04_memory_pressure.json`

**Story.** Tuesday, 10:00. Catalog is holding, there are no errors, but memory is hitting the request and the kernel is already throttling the process. No OOM yet.

**Input values.**

| Field | Value |
| --- | --- |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.memPsiPct` catalog | 2.4 |
| `golden.memReqPct` catalog | 93 |
| `golden.oomKills` catalog | 0 |
| `golden.cpuPsiPct / ioPsiPct` catalog | 0.3 / 0.1 |
| `golden.errPct` catalog | 0.2 |
| `precursorMatches[]` | empty |
| `saturationAsOfUnix` | 40 s ago |

**States.** 2 Fine. 3 Brewing (memPsiPct >= 1 and memReqPct >= 90). 4 Full. 5 Quiet.

**Expected decision: SCHEDULE.** Reason line: "catalog: memory is saturating, no OOM kill yet".

**Check.** Passed. Catalog is tier 2, so the rule "act now when lead < 30 min" does not apply. This is exactly "schedule": raise the request or find the leak within the sprint.

**What it revealed.** The hackathon brief promises "memory has been saturating for three days", but the API has only a current PSI snapshot. We cannot say "three days", only "pressure right now". Gap 2.

---

## S05. Cluster agent disconnected

`mock_data/s05_agent_disconnected.json`

**Story.** Wednesday, 15:20. The WebSocket from the cluster agent dropped at 14:33. Core is alive and serves the last known state. All counters look great.

**Input values.**

| Field | Value |
| --- | --- |
| `clusterAgentStats[digital-purchases].connected` | false, `lastMessageUnix` 47 min ago |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `serviceCoveragePct / servicesDark` | 100 / 0 (stale) |
| all `golden.*AsOfUnix` | 47 min ago (stale, threshold 5 min) |
| freshShare | 0% |
| `signalsHistory` last 9 buckets | missing |

**States.** 2 greyed (freshShare 0%). 3 greyed. 4 Blind (the agent is not connected). 5 greyed.

**Expected decision: BLIND.** Reason line: "cluster agent disconnected for 47 min, the fleet is not visible".

**Check.** Passed. This is the most important scenario for screening: a naive reading of `criticalOpen = 0` and `coverage = 100` would give a green screen while the fleet could be on fire.

**What it revealed.** `serviceCoveragePct` lies unless the agent connection is checked. Trust has to be read from two sources: whether there is a stream, and whether it is complete. That is why indicator 4 checks the connection first.

---

## S06. Log spike with no impact

`mock_data/s06_log_spike.json`

**Story.** Thursday, 11:00. After a library update, reporting writes 8.9 thousand error lines per hour. Requests go through, nobody noticed anything. In the old monitoring the pager goes off here.

**Input values.**

| Field | Value |
| --- | --- |
| `signalsByType` per hour | log 8 913, red 0, use 3, k8s 41 |
| `events` per hour | noise 8 790, signal 164, incident 0 |
| `LogErrorAnomaly` for reporting | yes, `errorCount 8 913` |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.errPct` reporting | 0.3 (2 rps) |
| `golden.errPct` the rest | 0.1–0.3 |
| errRecent / errBase | 0.20% / 0.20% |

**States.** 2 Fine. 3 Clear. 4 Full. 5 Quiet.

**Expected decision: ALL CLEAR.** Reason line: "reporting is noisy in logs, users are not affected".

**Check.** Passed. None of the five indicators reads `signalsByType.log` or `LogErrorAnomaly`, so the spike moves nothing. It is visible only in the drill-in of indicator 5, as attribution.

**What it revealed.** A log spike with no RED impact is an argument to do nothing, and the indicator set does this without a special rule. If we had added an "error log counter" as a sixth indicator, this scenario would break.

---

## S07. Checkout is down

`mock_data/s07_outage.json`

**Story.** Friday, 17:45. A certificate update broke the call from checkout to payments. The agent opened a critical incident 4 minutes ago.

**Input values.**

| Field | Value |
| --- | --- |
| `incidentMetrics.criticalOpen / warningOpen` | 1 / 0 |
| `incidents[0]` | checkout, `firstSeen` 4 min ago, `rca` "TLS handshake to payments fails" |
| `golden.errPct` checkout / payments | 38 / 12 |
| `ready` checkout | false, `componentsReady` 2 of 3 |
| failingShare | (85 × 38 + 60 × 12 + the rest × 0.2) / 1377 = 3.05% |
| blastMax of the affected | 0.62 (checkout) |
| `nodes[checkout].calledBy` | api-gateway, cart |
| `signalsHistory`: errRecent (2 h) / errBase / peak bucket | 0.31% / 0.20% / 2.99% |

**States.** 2 Broken (checkout is tier 1 with errPct >= 5 and ready = false). 3 Clear. 4 Full. 5 Quiet.

**Expected decision: ACT NOW.** Reason line: "checkout is down, 2 more services will be hit".

**Check.** Passed. A failingShare of 3.05% on its own would give only Degraded, but the tier-1 rule with errPct >= 5 raised it to Broken. The rule is needed: the 85 rps of checkout drown in the 420 rps of the gateway, although checkout is what brings in the money.

Indicator 5 says Quiet, and that is honest: until 17:41 the day really was quiet, and one bucket over 4 minutes does not move a two-hour window. The first version of the Settled rule looked only at the curve and gave "settled" with a critical incident open. Settled now requires `openNow = 0`.

**What it revealed.** A raw blastRadius of 0.62 tells the engineer nothing. "2 more services will be hit", derived from `calledBy`, tells everything. Turning the weight into words is mandatory. Second: indicators 2 and 5 do not duplicate each other, because 2 sees the minute and 5 sees the day.

---

## S08. Two services went silent

`mock_data/s08_dark_services.json`

**Story.** Saturday, 09:00. Scheduler and backup have not sent a single event in 6 hours. They are batch services and may simply be sleeping. Or they may have fallen into a CrashLoop in a namespace the agent does not see.

**Input values.**

| Field | Value |
| --- | --- |
| `serviceCoveragePct / services / servicesDark` | 83 / 12 / 2 |
| dark, as `knownServices` minus those reporting | scheduler, backup |
| `clusterAgentStats.connected` | true |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| everything else | normal |

**States.** 2 Fine. 3 Clear. 4 Partial (servicesDark 2, coverage 83). 5 Quiet.

**Expected decision: SCHEDULE.** Reason line: "scheduler and backup silent for 6 h: healthy or dead, unknown".

**Check.** Passed. The rule "Partial forbids ALL CLEAR" fired: without it the screen would be green while the backup might not have run for a week.

**What it revealed.** Zero events means two opposite states, and the API does not tell them apart. So a dark service is always work for a human, even on a Saturday. Debatable: whether a batch service with a "once a day" schedule should count as dark after 6 hours. The API has no expected event interval per service; this is a gap candidate.

---

## S09. Agent sees a failure 18 minutes out

`mock_data/s09_precursor_imminent.json`

**Story.** Monday, 14:05. Nothing is broken. But in payments the agent sees the same chain of events that ended in a token refresh storm three times this month. 4 of 5 steps are done.

**Input values.**

| Field | Value |
| --- | --- |
| `precursorMatches[0]` | service payments, pattern "token-refresh-storm", `confidence 0.84`, `matchedSteps 4`, `totalSteps 5` |
| `predictionAvgLeadMs` | 1 080 000 (18 min, overridden for this scenario) |
| `predictionPrecisionPct / hits / misses` | 78 / 31 / 9 |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.errPct` payments | 0.3 |
| `golden.memPsiPct` payments | 0.4 |

**States.** 2 Fine. 3 Brewing (confidence >= 0.7, 4/5 >= 0.5). 4 Full. 5 Quiet.

**Expected decision: ACT NOW.** Reason line: "payments: agent sees 4 of 5 steps to a failure, usually ~18 min of warning".

**Check.** Passed. Payments is tier 1 and lead < 30 min, so rule 3 of the roll-up gave ACT NOW with zero errors. This is the only scenario where ACT NOW comes from the future, not from the present.

**What it revealed.** `predictionAvgLeadMs` is an average per tenant, not per pattern. For a pattern that usually unfolds in 3 minutes, an 18 min average would give a false "schedule". We need a lead at the `patterns[]` level. A gap candidate.

---

## S10. Agent is confident but often wrong

`mock_data/s10_low_precision.json`

**Story.** The same match as in S09, but for another tenant, where the agent is in its second week and got it right 8 times out of 19.

**Input values.**

| Field | Value |
| --- | --- |
| `precursorMatches[0]` | service auth, `confidence 0.90`, `matchedSteps 4`, `totalSteps 5` |
| `predictionPrecisionPct / hits / misses` | 42 / 8 / 11 |
| `predictionAvgLeadMs` | 900 000 (15 min) |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| everything else | normal |

**States.** 2 Fine. 3 Pressure (Brewing lowered by one level, because precision < 60 with hits + misses >= 10). 4 Full. 5 Quiet.

**Expected decision: ALL CLEAR.** Reason line: "all normal; agent suspects auth but is wrong more often than right". The prediction ring is grey.

**Check.** Passed, but this is a deliberate decision, not an obvious one. The alternative, SCHEDULE "figure out why the agent is wrong", is meta-work on the agent, not on the fleet, and it does not belong on this screen.

**What it revealed.** Without `predictionPrecisionPct` indicator 3 would give ACT NOW on confidence 0.90, and after two false calls the engineer would turn the tracker off. Trust in the prediction is part of the indicator, not a separate metric. This is also the answer to "trust the data received" from the goal of the task.

---

## S11. Core restarted, no history yet

`mock_data/s11_no_history.json`

**Story.** Tuesday, 07:10. The Triage core restarted at 04:00. Everything it sees is healthy, but it has only three hours of history.

**Input values.**

| Field | Value |
| --- | --- |
| `signalsHistory` | 38 buckets (3.2 h) instead of 288 |
| `incidentMetrics.criticalOpen / warningOpen` | 0 / 0 |
| `golden.errPct` across all services | 0.1–0.3 |
| `precursorMatches[]` | empty |
| everything else | normal |

**States.** 2 Fine. 3 Clear. 4 Full. 5 — (fewer than 230 buckets).

**Expected decision: ALL CLEAR, dimmed.** Reason line: "all normal so far; only 3.2 h of history, the day cannot be judged yet".

**Check.** Passed after a fix. The first version of the roll-up ignored an unknown indicator and gave a plain ALL CLEAR here, although the rule says ALL CLEAR needs all four green. The obvious fix, SCHEDULE, is wrong too: there is no work to schedule, the history fills up by itself. The roll-up got rule 5: the decision stays "do nothing", the word is dimmed, and the reason line names what could not be judged.

**What it revealed.** The catalog notes that MTTR, MTTD and open counts live in core memory and reset on restart. The same is true for the 24 h history, so after every core restart the tracker is partly blind for most of a day, and the API gives no restart marker to explain why. A gap candidate. The same review found a second hole of this kind: absent resource-pressure fields were read as "no pressure". That one is a collection problem a human can fix, so it goes to indicator 4 as Partial and gives SCHEDULE.

---

## Summary

| Scenario | 2 Users | 3 Brewing | 4 Trust | 5 Day | Open | Decision | Decided by |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S01 quiet morning | Fine | Clear | Full | Quiet | 0 | ALL CLEAR | none |
| S02 release settled | Fine | Clear | Full | Settled | 0 | ALL CLEAR | none |
| S03 release regressed | Fine | Clear | Full | Regressed | 0 | SCHEDULE | 5 |
| S04 memory | Fine | Brewing | Full | Quiet | 0 | SCHEDULE | 3 |
| S05 agent disconnected | greyed | greyed | Blind | greyed | 0 | BLIND | 4 |
| S06 log spike | Fine | Clear | Full | Quiet | 0 | ALL CLEAR | none |
| S07 checkout is down | Broken | Clear | Full | Quiet | 1 crit | ACT NOW | 2 |
| S08 dark services | Fine | Clear | Partial | Quiet | 0 | SCHEDULE | 4 |
| S09 failure 18 min out | Fine | Brewing | Full | Quiet | 0 | ACT NOW | 3 |
| S10 agent is wrong | Fine | Pressure | Full | Quiet | 0 | ALL CLEAR | none |
| S11 no history yet | Fine | Clear | Full | — | 0 | ALL CLEAR, dimmed | none |

**Coverage.** Each of the three decisions occurs at least twice. Each of indicators 2–5 is the deciding one at least once. Indicator 1 never decides on its own, it only rolls up, and that is correct.

**How to reproduce.** Each scenario is a file in `mock_data/`. The rules of `metrics_spec.md` live in `backend/engine.py`; `mock_data/evaluate.py` runs them over every scenario and compares the result with the expected one, and `tests/` does the same plus both sides of every threshold. The data run caught two errors that the paper run missed (S03 and S07), so the table above reflects the state after both runs.

**What changed in `metrics_spec.md` after the run.**

1. The floor of the Regressed state in indicator 5 was lowered from 0.5% to 0.3% (S03, paper).
2. The errRecent window in indicator 5 was shortened from 6 to 2 h (S03, data).
3. The escalation in indicator 2 takes the maximum blastRadius instead of the sum (S03, data).
4. The Settled state in indicator 5 requires zero open incidents (S07, data).
5. The Partial state in indicator 4 got a mandatory reason line with the names of the dark services (S08): without names, "schedule" has no addressee.
6. The rule that downgrades a prediction at low precision is fixed as part of indicator 3, not as a separate indicator (S10).
7. An indicator that cannot be judged no longer passes as green: the roll-up got rule 5, ALL CLEAR dimmed (S11, code review).
8. Absent resource-pressure data makes indicator 3 unknown and indicator 4 Partial instead of reading as "no pressure" (code review).
9. A tier-1 service that is not ready is Broken even when its traffic data is stale (boundary tests).

**Gap candidates revealed by the run** (they extend section 5 in `metrics_catalog_triage.md`).

- There is no expected event interval per service, so a batch service cannot be told apart from a dead one (S08).
- `predictionAvgLeadMs` is an average per tenant, not per pattern (S09).
- There is no core restart marker, so a short history and reset counters cannot be explained on screen (S11).
