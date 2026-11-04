# daedalus-infra-health

Monitoring for a small fleet of VPSes. One screen answers one question: is everything fine, and if not, what to do.
Instead of raw metrics it shows a decision and the reason for it:

| Word on screen | Decision |
| --- | --- |
| **ALL CLEAR** | do nothing |
| **SCHEDULE** | plan the work, not today |
| **ACT NOW** | intervene now |
| **BLIND** | the data cannot be trusted, fix collection first |

Started at the "Self-Aware Infrastructure" hackathon, now running on real servers.
How it is built, deployed and changed is in [docs/FLEET.md](docs/FLEET.md).

## Parts

```
every host:  containers / k3s workloads / backup checks → agent (adapter/) ─┐  WireGuard
             logs → Alloy (logs/) ──────────────────────────────────────────┤
monitoring centre:  backend (verdict) → frontend      Loki (+ Grafana for now)
```

| Path | What it holds |
| --- | --- |
| [adapter/](adapter/) | The agent: finds every container (Docker) or workload (Kubernetes) on its host, reads cgroup pressure, host disk and memory, and results of outside checks; serves them as the Triage API (`/v2/agent/*`) |
| [backend/](backend/) | FastAPI: reads the agents, merges the fleet, decides (`bundle.py` → `engine.py` → `presentation.py`), keeps the decision journal |
| [frontend/](frontend/) | React, Tailwind, Vite. Renders the decision, computes nothing |
| [checks/](checks/) | Backup server checks: backup jobs, newest dumps, disk forecast, weekly test restore |
| [logs/](logs/) | Loki and Alloy configuration for every kind of host |
| [k8s/agent/](k8s/agent/) | The agent for a k3s cluster, deployed by Argo CD |
| [mock_data/](mock_data/), [scenarios.md](scenarios.md), [metrics_spec.md](metrics_spec.md) | Eleven scenarios with the expected decision, and the rules of the indicators; the tests run on them |
| [tests/](tests/) | pytest |

Deployment to servers is done by [Ansible-vps](https://github.com/ArturSkrin/Ansible-vps) (`playbooks/monitoring.yml`).
Images are built by [images.yml](.github/workflows/images.yml) and tagged with the commit sha.

## Compose files

| File | What it adds |
| --- | --- |
| `docker-compose.yaml` | backend and frontend |
| `docker-compose.agent.yaml` | the agent and the read-only Docker socket proxy |
| `docker-compose.agent-local.yaml` | wires the backend to the agents (`AGENTS=tenant=url,...`) |
| `docker-compose.fleet-logs.yaml` | Loki, Grafana and Alloy on the monitoring centre |
| `docker-compose.fleet-logs-dev.yaml` | the same on the dev VM (rootless Docker) |

## Tests

```bash
docker run --rm -v "$PWD:/src" -w /src python:3.12-slim sh -c "pip install -q -r backend/requirements-dev.txt && ruff check . && python -m pytest -q"
```

The scenario table, on Python 3.12+ with no packages: `python mock_data/evaluate.py`.

## Credits

The frontend design system (theme, rings, sparkline) comes from [AndriiShvaika/Daedalus-Hackathon-Front](https://github.com/AndriiShvaika/Daedalus-Hackathon-Front).
