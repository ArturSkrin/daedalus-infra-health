# daedalus-infra-health

Infra Health Tracker for the "Self-Aware Infrastructure" hackathon. A fitness tracker for infrastructure: not a dashboard the engineer reads a cause from, but a screen that shows the decision the Triage agent has already made, and the grounds to believe it.

![Main screen, scenario S07](design/desktop_s07_outage.png)

## Goal

The engineer opens the tracker in the morning and after a release. Within seconds they should see one of three:

| Word on screen | Decision |
| --- | --- |
| **ALL CLEAR** | do nothing |
| **SCHEDULE** | plan the work, not today |
| **ACT NOW** | intervene now |

Plus a service state, **BLIND**: the data cannot be trusted, fix collection first.

The main screen has five indicators, and none of them is a raw metric:

1. **Fleet state**: one word, a roll-up of the other four by priority rules.
2. **Users now**: are people hurting right now (RED as a state).
3. **What's brewing**: the only indicator from the future (the agent's precursors plus resource pressure).
4. **Can we trust it**: is there a data stream, and is it complete.
5. **How the day went**: the value on a quiet day, and also the quiet regression after a release.

## How to view the prototype

Only Docker is needed.

```bash
docker compose up -d --build
```

The tracker opens at http://localhost:8080. If the port is taken, set another one:

```bash
TRACKER_PORT=8088 docker compose up -d --build
```

Switch scenarios with the list in the header or with a URL parameter. The drill-in opens by tapping a tile, a ring or the word, and also with the `drill` parameter:

```
/?scenario=s07_outage
/?scenario=s09_precursor_imminent&drill=forecast
```

Values of `drill`: `users`, `forecast`, `trust`, `day`, `verdict`. PNG exports of all eleven scenarios and five drill-ins are in [design/](design/).

After a merge into `main` the same prototype is built for GitHub Pages by [pages.yml](.github/workflows/pages.yml). There is no backend there, so the screen models are exported to static JSON by the same engine, and the frontend reads them instead of the API.

## How to reproduce the scenarios

The rules of the five indicators live in one place, [backend/engine.py](backend/engine.py), and every threshold in [backend/thresholds.py](backend/thresholds.py). 181 tests check them:

- the decision, the states and the reason line on screen for each of the eleven scenarios;
- both sides of every threshold (0.49% and 0.5%, 29 and 30 minutes of warning, 94% and 95% coverage);
- 35 kinds of incomplete data on two scenarios: the backend never crashes and always gives a decision;
- the HTTP API, the response contract, and live mode against a fake core;
- the compose shim: what the tracker finally says when EVE is healthy, unpatched, down, recovering, or restarted.

```bash
docker run --rm -v "$PWD:/src" -w /src python:3.12-slim sh -c "pip install -q -r backend/requirements-dev.txt && python -m pytest -q"
```

In Git Bash on Windows put `MSYS_NO_PATHCONV=1` in front of the command, otherwise the `/src` path gets converted.

The same as a table, without Docker, on Python 3.12+ with no packages:

```bash
python mock_data/evaluate.py
```

```
scenario                  users       forecast    trust       day           verdict       ok
s01_calm                  ok          clear       full        quiet         all_clear     ✓
s03_release_regressed     ok          clear       full        regressed     schedule      ✓
s05_agent_disconnected    unknown     unknown     blind       unknown       blind         ✓
s07_outage                broken      clear       full        quiet         act_now       ✓
...
11/11 scenarios match metrics_spec.md
```

One scenario with the intermediate numbers: `python mock_data/evaluate.py s03`. Regenerate the mock data: `python mock_data/generate.py`.

## Architecture

```
mock_data/*.json ─┐
                  ├─► bundle.py ─► engine.py ─► presentation.py ─► /api ─► frontend (React)
Triage API ───────┘   reads raw     rules and     words, captions,          renders only
                      JSON          thresholds    drill-in
```

- **bundle.py** is the only module that reads raw Triage JSON. The catalog warns that the core omits fields it has nothing to report for, so a missing or malformed field becomes an explicit "not measured" here, not a zero and not an exception.
- **thresholds.py** holds every threshold under the names used in the spec. The "How this indicator decides" text on screen is generated from the same numbers.
- **engine.py** decides. It takes the normalised Bundle and returns the states of the four indicators, the decision, the rule that fired, and every fact the wording needs. An indicator that cannot be measured is "unknown", never green.
- **presentation.py** turns the decision into human language: the word, the reason line, tile captions, ring fill, drill-in content, the queue. It holds no thresholds and never re-derives a decision.
- **schemas.py** is the response contract. FastAPI validates every response against it, and the frontend types in `frontend/src/api.gen.ts` are generated from the OpenAPI document with `npm run gen:types`. CI fails when the generated files lag behind the code.
- **frontend** computes nothing and knows no threshold. Raw values appear only in the drill-in.
- **live.py** assembles the same five blocks from a real Triage core. Live mode is switched on with `TRIAGE_BASE_URL`, `TRIAGE_TOKEN` and `TRIAGE_TENANT`, after which "Live data" appears in the scenario list. Requests to the core run in parallel, the answer is cached for 20 seconds, and the core's error text is never passed to the client. Without access to the organizers' core this path has not been run on live data.

## Live mode on a real application

The tracker reads a Triage core. For an application that has no Triage agent there is a compose shim in [adapter/](adapter/): a small service that serves the same five `/v2/agent/*` endpoints, built from HTTP probes and from what the app can report about itself, including PSI read from its own cgroup. The backend is not aware of it; live mode is simply pointed at the shim.

```bash
docker compose -f docker-compose.yaml -f docker-compose.eve.yaml up -d --build
```

This wires the tracker to [EVE Online Tools](https://github.com/ArturSkrin/Eve-Online-Tools) running under compose on the same host, over EVE's `proxy` network. The three steps on the EVE side, and what the screen says after each of them (BLIND, then SCHEDULE, then ALL CLEAR), are in [integrations/eve-tools/](integrations/eve-tools/). The shim reports readiness, traffic, errors and resource pressure. It does not do the agent's work: no event classification, no precursors, no RCA. The end-to-end run was checked against a stand-in for EVE on the same network names ([design/live_eve_healthy.png](design/live_eve_healthy.png), [design/live_eve_down.png](design/live_eve_down.png)), not yet against the real EVE stack.

Kubernetes deployment is described in [k8s/](k8s/); images are built by [images.yml](.github/workflows/images.yml).

## Repository layout

| Path | What it holds |
| --- | --- |
| [metrics_spec.md](metrics_spec.md) | The five indicators: effect on the decision, thresholds, API fields and formulas, horizon, trust indicator, drill-in |
| [scenarios.md](scenarios.md) | Eleven scenarios with input values, states, the expected decision, and what each run revealed |
| [mock_data/](mock_data/) | One JSON per scenario in the shape of the Triage API, the generator, the rule check, instructions |
| [design_rationale.md](design_rationale.md) | Why these five, why not others, gaps in the catalog |
| [metrics_catalog_triage.md](metrics_catalog_triage.md) | The catalog sorted into three groups: changes the decision, explains it, changes nothing |
| [design/](design/) | PNGs of the main screen for every scenario, the drill-ins, the watch faces |
| [adapter/](adapter/) | Triage-compatible shim for compose applications without an agent |
| [integrations/eve-tools/](integrations/eve-tools/) | What to add to EVE Online Tools: a vitals endpoint and a compose override |
| [backend/](backend/) | FastAPI: bundle, thresholds, engine, presentation, schemas, live, static and OpenAPI export |
| [frontend/](frontend/) | React, Tailwind, Vite |
| [tests/](tests/) | pytest: scenarios, threshold boundaries, incomplete data, API |
| [k8s/](k8s/) | Cluster manifests |
| [reference/](reference/) | The original Triage metrics catalog from the organizers |

## Requirements checklist

| Requirement | Status | Where |
| --- | --- | --- |
| No more than 5 indicators on the main screen | exactly 5; the queue is a list, not an indicator; a test checks the count | metrics_spec.md, tests/ |
| For each indicator: which decision it changes, the threshold, the API fields | yes | metrics_spec.md |
| At least one indicator with a horizon in the future | What's brewing, through `precursorMatches` and PSI | metrics_spec.md, section 3 |
| It is visible when the data cannot be trusted | Can we trust it, the BLIND state, the source and data-age pill in the header | design/phone_s05_agent_disconnected.png |
| A state that means "all good" exists | ALL CLEAR in S01, S02, S06, S10; dimmed in S11 | design/phone_s01_calm.png |
| No framework names or raw values on the main screen | errPct, PSI, p99, blastRadius only in the drill-in; a test checks it | design/drill_users_s07.png |
| USE, RED, SIG became a state, not menu sections | yes | design_rationale.md |
| Main screen plus one level deep | a tile, a ring or the word opens the drill-in | design/drill_*.png |
| Phone and watch | five indicators and the queue without scrolling at 390×844; three watch faces | design/phone_*.png |
| At least 8 scenarios with input values and a decision | 11 scenarios, 181 tests | scenarios.md, tests/ |
| Mock data for each scenario, with instructions | deterministic, with a check | mock_data/ |
| A log error spike with no RED impact leads to "nothing" | scenario S06 | scenarios.md |
| Silent services are not mistaken for healthy ones | scenarios S05 and S08 | scenarios.md |
| The metrics catalog sorted into three groups | yes | metrics_catalog_triage.md |
| Gaps found in the catalog | 9, three submitted for the nomination | design_rationale.md |
| Implementation on live data | live mode runs end to end on a compose application through the shim (probes, real request counters, PSI from cgroup); not run against the organizers' Triage core | adapter/, integrations/eve-tools/, tests/test_adapter.py |

## Credits

The frontend design system (theme, rings, sparkline) comes from [AndriiShvaika/Daedalus-Hackathon-Front](https://github.com/AndriiShvaika/Daedalus-Hackathon-Front). The FastAPI backend, the tests and the Docker build were started in the `feat/web-demo` branch.
