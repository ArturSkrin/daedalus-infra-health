# Connecting EVE Online Tools to the tracker

[Eve-Online-Tools](https://github.com/ArturSkrin/Eve-Online-Tools) runs under docker compose as `nginx -> app -> db`, and the app calls the public EVE ESI API. It has no Triage agent, so the tracker watches it through the compose shim in [`adapter/`](../../adapter/): a small service that speaks the Triage API and builds its answers from probes and from what the app can tell about itself. The tracker backend is not changed at all; live mode is pointed at the shim.

## What the shim can and cannot say

| Indicator | Source | Works |
| --- | --- | --- |
| Users now | probes of nginx and the app, plus the app's own `/api` request and 5xx counters | yes |
| What's brewing, resource pressure | PSI, memory and OOM kills from the app container's own cgroup v2 | yes, after step 2 |
| What's brewing, precursors | none: finding patterns is the Triage agent's work | no, left empty on purpose |
| Can we trust it | which services answer, how fresh the data is | yes |
| How the day went | 24 h of requests and errors, kept on a volume so a restart does not erase the day | yes, after about 19 h of history |
| Queue | one rule: a service that stops answering for two cycles opens an incident, and answering again closes it | yes |

The shim does not classify events, write an RCA or predict anything. Where a real Triage core would know more, the fields are left out, and the tracker shows them as not measured.

## Step 0. Nothing changed in EVE

```bash
docker compose -f docker-compose.yaml -f docker-compose.eve.yaml up -d --build
```

Run this in the tracker repository with the EVE stack already up: the override joins EVE's network as an external one. Then open the tracker. With a live source configured it opens live data by itself; the demo scenarios stay in the list in the header, and `/?live=1` or `/?scenario=s07_outage` force either one.

Both `-f` files are required. A plain `docker compose up` starts the tracker in demo mode only: no collector, and `/?live=1` answers "live mode is not configured".

Check the app's port first. It listens on `APP_PORT` from EVE's `.env`, which is not in its repository. `docker ps` shows it: the app container lists that port next to the Dockerfile's 5000, for example `3000/tcp, 5000/tcp`. If it is not 5000, say so, otherwise the collector gets a refused connection and reports the app as down:

```bash
EVE_APP_URL=http://app:3000 docker compose -f docker-compose.yaml -f docker-compose.eve.yaml up -d --build
```

EVE's compose file declares one named network, `proxy`, and only `nginx` is attached to it. `app` and `db` sit on the project's private default network. So at this step the shim sees one service of two and the screen says **BLIND**: not enough of the fleet is reporting. That is the honest answer, not a bug.

## Step 1. Let the collector reach the app

Already in EVE's `main`: [`docker-compose.override.yaml`](docker-compose.override.yaml) sits next to its `docker-compose.yaml`, and compose merges it by itself. It attaches `app` to `proxy`. The database stays private on purpose.

The screen now judges users from probes and says **SCHEDULE**: resource pressure is not collected, so the forecast is blind. That is a real task for a human, which is step 2.

## Step 2. Let the app speak for itself

Already in EVE's `main`: [`vitals.ts`](vitals.ts) is `server/vitals.ts` there, wired into `server/index.ts` right after the body parsers. For another Express app it is the same file plus three lines:

```ts
import { vitalsMiddleware, registerVitals } from "./vitals";
app.use(vitalsMiddleware);
registerVitals(app);
```

Pull and rebuild EVE (`git pull && docker compose up -d --build`). `GET /internal/vitals` now returns cumulative request, error and duration counters for `/api`, the state of the database connection, and PSI, memory and OOM kills read from the container's own cgroup. No privileges and no `docker.sock` are involved: a container can always read its own cgroup files. This is the same idea the hackathon brief describes for USE, done from the inside.

With this the fleet is three services (`db` is discovered through the app), trust is **Full**, and the screen says **ALL CLEAR**, dimmed until a day of history exists.

## Keep /internal/ off the internet

EVE's nginx listens on a public port and its config is not in the repository; the k8s ingress forwards every path too. So the endpoint protects itself first: it answers 404 to any request carrying `X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Host` or `Forwarded`, which is every request that came through a reverse proxy configured the usual way. The collector calls the app directly over the Docker network and carries none of them. That is a safety net, not a guarantee: a proxy that sets no such header would pass. Check from outside (`curl -i http://<server>/internal/vitals` must be 404), and for certainty do one of these:

- add `location /internal/ { return 404; }` to the public server block, or
- set `VITALS_TOKEN` in EVE's `.env` and the same value in the tracker's environment; without the token the endpoint answers 404.

## Verifying the whole chain

Run these on the host where both stacks live. `TR` is shorthand for the tracker's compose command, `EVE` for EVE's.

```bash
TR="docker compose -f docker-compose.yaml -f docker-compose.eve.yaml"   # in the tracker folder
EVE="docker compose"                                                  # in the EVE folder
```

| # | Do | Expect on the screen | Proves |
| --- | --- | --- | --- |
| 1 | open `/debug/targets` on the collector (command below) | every target `reachable`, `app` has `hasVitals: true`, `db` is `known` | network and endpoint |
| 2 | open the tracker | **ALL CLEAR**, dimmed; Can we trust it: "seeing all 3 services"; header pill says Live · eve-tools | the happy path |
| 3 | `for i in $(seq 200); do curl -s -o /dev/null http://localhost/api/scan/progress; done` | Users now drill-in: `app` traffic jumps from ~0.07/s to several per second | real request counters, not only probes |
| 4 | `$EVE stop app` | within 30 s **ACT NOW**, "app is down" or "nginx is down", two critical incidents in the queue | outage detection |
| 5 | `$EVE start app` | within about a minute back to **ALL CLEAR**; the incident moves to "Handled by the agent today" | auto-resolve, probes ageing out |
| 6 | `$EVE stop db`, wait 30 s, then `$EVE start db` | **ACT NOW**, reason names `app`; a warning incident for `db` | the database is watched through the app |
| 7 | `docker update --cpus 0.2 eve-online-tools-app-1`, then `docker exec eve-online-tools-app-1 sh -c 'for i in 1 2 3 4; do (timeout 180 sh -c "while :; do :; done" &) ; done'` | after 1 to 2 min What's brewing: **Brewing**, "app: CPU stall is slowing it down", word **SCHEDULE**; undo with `docker update --cpus 0 ...` | USE through PSI from the container's own cgroup |
| 8 | `docker update --memory 400m --memory-swap 400m eve-online-tools-app-1` | What's brewing drill-in shows "Mem vs request" for `app` | memory share appears only with a limit |
| 9 | `$TR restart collector` | "h of history" in the reason line keeps growing instead of resetting | history persists on the volume |
| 10 | `$TR stop collector` | within 30 s the tracker shows an error banner, not a green screen | a dead collector is never read as calm |
| 11 | from another machine: `curl -i http://<server>/internal/vitals` | `404` | the endpoint is not public |
| 12 | leave it running for 19 h | How the day went turns from — to **Quiet**, and ALL CLEAR is no longer dimmed | the day indicator needs a day |

Step 7 needs a CPU limit because pressure is time spent waiting for a resource: on an idle multi-core host four busy loops wait for nothing, and PSI stays at zero however hot the CPU runs. That is the point the hackathon brief makes about PSI against utilisation.

## When a target stays dark

```bash
docker compose -f docker-compose.yaml -f docker-compose.eve.yaml exec collector \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/debug/targets').read().decode())"
```

It lists, per target, whether the name resolves, what answered, and whether vitals were found. "name does not resolve on this network" means the container is not attached to `proxy`. If another stack on `proxy` also has a service called `nginx` or `app`, set `ADAPTER_TARGETS` to a JSON list with container names instead of service names (see `adapter/config.py` for the shape).

Two behaviours worth knowing:

- A service the collector has never seen is *dark*: it counts against trust, never as an error. A service it has seen whose name then disappears is *down*: under compose a name leaves the network only when the container stops.
- A hobby-scale app gets a few requests a minute, so one failed request is not reported as "20% of users". An error share is shown from three errors, or from fifty requests, in five minutes.
