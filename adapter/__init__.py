"""A Triage-compatible shim for services that have no Triage agent.

The tracker reads five endpoints of a Triage core. This package serves the same
five endpoints, built from what a plain docker-compose application can tell
about itself: HTTP probes, an optional in-app vitals endpoint (request counters
and cgroup v2 pressure), and TCP reachability. The tracker backend needs no
change: point TRIAGE_BASE_URL at this service.

What the shim does NOT do is the agent's real work: it classifies no events,
finds no precursors and writes no RCA. It reports readiness, traffic, errors and
resource pressure, and opens an incident only when a service stops answering,
which mirrors the one rule in the catalog that opens incidents (AppDegraded).
"""
