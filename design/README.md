# design

Exports of the working prototype. Every PNG here is a capture of the real screen rendering one of the scenarios in `mock_data/`, not a mockup. The prototype itself is in `frontend/`; see the root README for how to run it.

## Main screen, phone (390 × 844)

All five indicators and the queue fit without scrolling.

| Scenario | Decision | File |
| --- | --- | --- |
| S01 Quiet morning | ALL CLEAR | [phone_s01_calm.png](phone_s01_calm.png) |
| S02 Release settled | ALL CLEAR | [phone_s02_release_settled.png](phone_s02_release_settled.png) |
| S03 Release regressed quietly | SCHEDULE | [phone_s03_release_regressed.png](phone_s03_release_regressed.png) |
| S04 Memory is saturating | SCHEDULE | [phone_s04_memory_pressure.png](phone_s04_memory_pressure.png) |
| S05 Cluster agent disconnected | BLIND | [phone_s05_agent_disconnected.png](phone_s05_agent_disconnected.png) |
| S06 Log spike with no impact | ALL CLEAR | [phone_s06_log_spike.png](phone_s06_log_spike.png) |
| S07 Checkout is down | ACT NOW | [phone_s07_outage.png](phone_s07_outage.png) |
| S08 Two services went silent | SCHEDULE | [phone_s08_dark_services.png](phone_s08_dark_services.png) |
| S09 Agent sees a failure 18 minutes out | ACT NOW | [phone_s09_precursor_imminent.png](phone_s09_precursor_imminent.png) |
| S10 Agent is confident but often wrong | ALL CLEAR | [phone_s10_low_precision.png](phone_s10_low_precision.png) |
| S11 Core restarted, no history yet | ALL CLEAR, dimmed | [phone_s11_no_history.png](phone_s11_no_history.png) |

## Main screen, desktop, with the three watch faces

[desktop_s01_calm.png](desktop_s01_calm.png) · [desktop_s07_outage.png](desktop_s07_outage.png) · [desktop_s09_precursor_imminent.png](desktop_s09_precursor_imminent.png)

## One level deep

The drill-in is where raw values are allowed: error rates, stall percentages, p99, pattern steps.

| Indicator | File |
| --- | --- |
| Fleet state: the priority rules, fired one highlighted | [drill_verdict_s07.png](drill_verdict_s07.png) |
| Users now: services by error rate and who gets hit next | [drill_users_s07.png](drill_users_s07.png) |
| What's brewing: pattern steps and the agent's track record | [drill_forecast_s09.png](drill_forecast_s09.png) |
| Can we trust it: agent link, coverage, silent services | [drill_trust_s08.png](drill_trust_s08.png) |
| How the day went: 24 h of failing requests, what the agent handled | [drill_day_s03.png](drill_day_s03.png) |

## Reading the screen

- The four rings are the four vitals, outermost first: Users now, What's brewing, Can we trust it, How the day went. A full green ring is a closed ring. Colour is the decision, never decoration: green nothing, amber schedule, red act now, grey unknown.
- The word under the rings is the decision. The line under the word says which indicator produced it, in one sentence.
- The tile with the coloured border is the one that drives the verdict.
- The pill in the header says where the data came from and how old it is. It turns red when the cluster agent is gone.

## Regenerating the PNGs

```bash
TRACKER_PORT=8088 docker compose up -d --build
bash design/tools/screenshots.sh
```
