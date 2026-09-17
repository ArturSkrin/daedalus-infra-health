# mock_data

Ten mock data sets, one per scenario in `scenarios.md`. Each file follows the shape of the Triage API responses from the metrics catalog, so the backend reads a mock file and a live core with the same code.

## Files

| File | Scenario | Expected decision |
| --- | --- | --- |
| `s01_calm.json` | Quiet morning | ALL CLEAR |
| `s02_release_settled.json` | Release settled | ALL CLEAR |
| `s03_release_regressed.json` | Release regressed quietly | SCHEDULE |
| `s04_memory_pressure.json` | Memory is saturating | SCHEDULE |
| `s05_agent_disconnected.json` | Cluster agent disconnected | BLIND |
| `s06_log_spike.json` | Log spike with no impact | ALL CLEAR |
| `s07_outage.json` | Checkout is down | ACT NOW |
| `s08_dark_services.json` | Two services went silent | SCHEDULE |
| `s09_precursor_imminent.json` | Agent sees a failure 18 minutes out | ACT NOW |
| `s10_low_precision.json` | Agent is confident but often wrong | ALL CLEAR |

`index.json` lists the scenarios for the switcher in the prototype.

## Shape of one file

```
{
  "scenario": "s03_release_regressed",
  "title": "...", "tenant": "digital-purchases", "now": "2026-09-14T13:10:00+03:00",
  "story": "...",
  "expected": { "verdict": "schedule", "reason": "...", "states": { "users": "ok", "forecast": "clear", "trust": "full", "day": "regressed" } },
  "status":       { ...  GET /v2/agent/status  (tenantStats.tenants[tenant], clusterAgentStats, unmapped*) },
  "incidents":    { ...  GET /v2/agent/incidents?tenant= },
  "applications": [ ...  GET /v2/agent/applications?tenant= ],
  "graph":        { ...  GET /v2/agent/graph?tenant= },
  "analytics":    { ...  GET /v2/agent/analytics?tenant= }
}
```

The `expected` block is not part of the API. Only the tests and the "Why this word" drill-in read it.

State codes used in `expected` and returned by the engine:

| Indicator | Codes | On screen |
| --- | --- | --- |
| verdict | `all_clear`, `schedule`, `act_now`, `blind` | ALL CLEAR, SCHEDULE, ACT NOW, BLIND |
| users | `ok`, `degraded`, `broken` | Fine, Degraded, Broken |
| forecast | `clear`, `pressure`, `brewing` | Clear, Pressure, Brewing |
| trust | `full`, `partial`, `blind` | Full, Partial, Blind |
| day | `quiet`, `settled`, `regressed` | Quiet, Settled, Regressed |
| any | `unknown` | — |

## Fields that are not in the catalog

Three fields were added because the screen needs them and the catalog has no equivalent. Each one is a candidate gap, and each is marked with a comment in `generate.py`.

- `precursorMatches[].matched` and `.remaining`: the step texts. The catalog has only the counters `matchedSteps` and `totalSteps`.
- `darkServices[]` in S08: names and last event time. The catalog has only the count `servicesDark`.
- `topSignalSources[]` in S06: which service produced the log storm. The catalog says log volume is never stored per service.

The catalog says a missing field means "not measured". The mock data reproduces that: batch services (`scheduler`, `backup`) have no `reqPerSec / errPct / rateAsOfUnix` block, in S08 they are absent from `applications` entirely, and in S05 every `*AsOfUnix` is 47 minutes stale.

## How to view it with the prototype

```bash
docker compose up -d --build
```

Open http://localhost:8080 and pick a scenario in the header, or use the URL:

```
/?scenario=s03_release_regressed
/?scenario=s03_release_regressed&drill=day
```

Tapping the verdict word opens "Why this word": the priority rules with the fired one highlighted, plus the expected and computed decision for the scenario side by side.

## How to check the rules without the prototype

The rules live in `backend/engine.py`. `evaluate.py` is a thin command-line wrapper around it and needs only Python 3.12+, no packages.

```bash
python mock_data/evaluate.py
python mock_data/evaluate.py s03     # one scenario with the intermediate numbers
```

The same checks run as tests, together with a check that the reason line on screen matches `expected.reason`:

```bash
python -m pytest -q
```

## How to regenerate

```bash
python mock_data/generate.py
```

Everything is deterministic: one shared fixture of 12 services and a seed per scenario. Scenario overrides live in the function with the scenario number; everything else is inherited from the fixture. After changing the fixture or a threshold, run the tests: they fail if any scenario disagrees with its expectation.
