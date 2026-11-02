#!/usr/bin/env python3
"""Backup checks for Daedalus, run by systemd timers on the backup server as root. Standard library only.

    daedalus_checks.py hourly    the backup jobs, the newest dump of every database, the disk forecast
    daedalus_checks.py restore   restore the newest dump of every database into a throwaway postgres (weekly)

Whether a database answers is not checked here: the application knows that first and says so through its
readiness. Here we answer what nobody knows until the day it is needed: is there a recent, readable,
restorable backup, and will the disk still have room for tomorrow's.

Every database is a directory under postgresDir; nothing is configured per database and no credentials are needed.
Each check writes <output>/<name>.json, which the Daedalus agent on this host reads as a target
(adapter/checks_source.py). Config, all optional: /etc/daedalus-checks/config.json

    {"output": "/var/lib/daedalus-checks", "postgresDir": "/var/backups/postgres", "pattern": "*.dump",
     "jobs": ["postgres-backup", "file-backup"], "restoreImage": "postgres:17", "maxDumpAgeH": 26, "disk": "/"}
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

CONFIG = Path("/etc/daedalus-checks/config.json")
HOURLY_MAX_AGE_S = 3 * 3600         # an hourly check silent for three hours: its timer is broken
RESTORE_MAX_AGE_S = 8 * 24 * 3600   # weekly, with a day to spare
FORECAST_MIN_DAYS = 7               # fewer daily samples than this is not a trend
SHRINK_RATIO = 0.5                  # a dump at half its usual size lost data somewhere
ERROR_LINE = re.compile(r"error|fail|denied|refused|verification|timeout", re.I)
COUNT_ROWS = ("SELECT count(*), coalesce(sum((xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I',"
              " table_schema, table_name), false, true, '')))[1]::text::bigint), 0) FROM information_schema.tables"
              " WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')")


# --------------------------------------------------------------- judgement ---
# Pure functions: everything the screen will say is decided here, and tested.

def gb(size: float) -> str:
    return f"{size / 1e9:.2f} GB" if size >= 1e8 else f"{size / 1e6:.1f} MB"


def judge_dump(dump: str, age_h: float, size: int, previous: list[int], readable: bool, error: str,
               max_age_h: float) -> tuple[bool, str]:
    if age_h > max_age_h:
        return False, f"newest dump is {age_h:.0f} h old: backups stopped ({dump})"
    if not readable:
        return False, f"{dump} is unreadable: {error}"
    usual = statistics.median(previous[-7:]) if previous else None
    if usual and size < SHRINK_RATIO * usual:
        return False, f"{dump} is {gb(size)}, {100 * size / usual:.0f}% of the usual {gb(usual)}: data is missing"
    grew = f", {size / usual:.0f}× the usual {gb(usual)}" if usual and size > 3 * usual else ""    # growth is news, not a fault
    return True, f"{dump}: {gb(size)}, {age_h:.0f} h old{grew}"


def judge_job(props: dict, error_line: str | None, now: float) -> tuple[bool, str]:
    """props: systemctl show of the job's service. The timer's own state does not matter: the last run does."""
    state = props.get("LoadState")
    if state != "loaded":       # a renamed or misspelled job must not look like one that simply has not run yet
        return False, "no such systemd unit" if state == "not-found" else f"cannot read the unit ({state or 'systemctl failed'})"
    finished = props.get("ExecMainExitTimestampMonotonic", "0") != "0"
    if not finished:
        return True, "has not run since the server started"
    when = _ago(now - int(props.get("ExecMainExitTimestamp_unix", now)))
    if props.get("Result") == "success":
        return True, f"last run {when} ago: ok"
    reason = f": {error_line}" if error_line else ""
    return False, f"last run {when} ago failed (exit {props.get('ExecMainStatus', '?')}){reason}"


def forecast(history: list[list]) -> tuple[float | None, float]:
    """Days until the disk is full, by a least-squares line through daily [day_number, used, total] samples."""
    points = history[-30:]
    if len(points) < 2:
        return None, 0.0
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    spread = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / spread if spread else 0.0
    if slope <= 0:
        return None, slope
    return (points[-1][2] - points[-1][1]) / slope, slope


def judge_forecast(history: list[list]) -> tuple[bool, int, str]:
    """(ok, tier, detail): two weeks of room is work to schedule, three days is a page."""
    if len(history) < FORECAST_MIN_DAYS:
        return True, 2, f"collecting history: {len(history)} of {FORECAST_MIN_DAYS} days"
    days, slope = forecast(history)
    if days is None:
        return True, 2, "not filling up over the last 30 days"
    detail = f"full in about {days:.0f} days at {gb(slope)} a day"
    if days < 3:
        return False, 1, detail
    return days >= 14, 2, detail


def judge_restore(dump: str, restore_rc: int, errors: int, tables: int, rows: int, seconds: float) -> tuple[bool, str]:
    """Restored is not enough: an empty dump restores perfectly and saves nothing."""
    facts = f"{tables} tables, {rows} rows in {seconds / 60:.0f} min" + (f", {errors} restore errors ignored" if errors else "")
    if tables == 0 or rows == 0:
        return False, f"{dump} restores to nothing ({facts})"
    if restore_rc != 0 and errors > tables:
        return False, f"{dump} restored with more errors than tables ({facts})"
    return True, f"{dump} restores: {facts}"


def _ago(seconds: float) -> str:
    return f"{seconds / 3600:.0f} h" if seconds >= 3600 else f"{seconds / 60:.0f} min"


# ------------------------------------------------------------------- output ---

def result(name: str, ok: bool, detail: str, tier: int, max_age_s: int, now: float) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "tier": tier, "checkedAtUnix": now, "maxAgeS": max_age_s}


def write(output: Path, item: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    path = output / (item["name"].replace("/", "-") + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(item), encoding="utf-8")
    temporary.replace(path)                     # the agent never reads half a file


def dumps(directory: Path, pattern: str) -> list[Path]:
    """Oldest first."""
    return sorted((p for p in directory.glob(pattern) if p.is_file()), key=lambda p: p.stat().st_mtime)


# ------------------------------------------------------------------ the host ---

def _run(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def parse_props(text: str, now: float, monotonic_now: float) -> dict:
    """systemd before 251 has no --timestamp=unix (Ubuntu 22.04 ships 249): wall time comes from the monotonic stamps."""
    props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    for key in ("ExecMainStartTimestamp", "ExecMainExitTimestamp"):
        usec = int(props.get(f"{key}Monotonic") or 0)
        props[f"{key}_unix"] = str(int(now - (monotonic_now - usec / 1e6))) if usec else "0"
    return props


def job_props(unit: str, now: float) -> dict:
    shown = _run("systemctl", "show", f"{unit}.service", "-p", "LoadState", "-p", "Result", "-p", "ExecMainStatus",
                 "-p", "ExecMainStartTimestampMonotonic", "-p", "ExecMainExitTimestampMonotonic")
    return parse_props(shown.stdout, now, time.monotonic())     # CLOCK_MONOTONIC, the clock systemd stamps with


def job_error(unit: str, started_unix: str) -> str | None:
    """The first line of the last run that looks like the cause, not systemd's own \"Failed with result\"."""
    since = ["--since", f"@{started_unix}"] if started_unix != "0" else ["-n", "40"]
    lines = _run("journalctl", "-u", f"{unit}.service", *since, "--no-pager", "-o", "cat").stdout.splitlines()
    causes = [line.strip() for line in lines if ERROR_LINE.search(line) and not line.startswith(f"{unit}.service:")]
    return causes[0][:200] if causes else None


def readable(image: str, dump: Path) -> tuple[bool, str]:
    """pg_restore --list reads the archive's table of contents: a truncated or corrupt file fails in seconds."""
    listed = _run("docker", "run", "--rm", "--network", "none", "-v", f"{dump}:/dump:ro", image, "pg_restore", "--list", "/dump")
    return listed.returncode == 0, (listed.stderr.strip().splitlines() or [""])[-1][:200]


def restore(image: str, name: str, dump: Path) -> tuple[bool, str]:
    container = f"daedalus-restore-{name.lower()}"
    _run("docker", "rm", "-f", container)
    started_at = time.monotonic()
    try:
        # no network, no published port, trust auth inside: the container exists only for this run
        started = _run("docker", "run", "-d", "--rm", "--name", container, "--network", "none",
                       "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-v", f"{dump}:/restore.dump:ro", image)
        if started.returncode != 0:
            return False, f"cannot start {image}: {started.stderr.strip()[:200]}"
        for _ in range(60):
            # over TCP: the image's init phase runs a socket-only server that is ready too, then stops it mid-restore
            if _run("docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-q").returncode == 0:
                break
            time.sleep(1)
        restored = _run("docker", "exec", container, "pg_restore", "-U", "postgres", "-d", "postgres",
                        "--no-owner", "--no-acl", "/restore.dump", timeout=3 * 3600)
        counted = _run("docker", "exec", container, "psql", "-U", "postgres", "-tAF", " ", "-c", COUNT_ROWS)
        tables, rows = (int(x) for x in (counted.stdout.split() or ["0", "0"])[:2])
        return judge_restore(dump.name, restored.returncode, restored.stderr.count("error:"), tables, rows,
                             time.monotonic() - started_at)
    finally:
        _run("docker", "rm", "-f", container)


# --------------------------------------------------------------------- runs ---

def hourly(config: dict, output: Path, now: float) -> None:
    for unit in config.get("jobs", []):
        props = job_props(unit, now)
        ok, detail = judge_job(props, job_error(unit, props["ExecMainStartTimestamp_unix"]), now)
        write(output, result(f"job/{unit}", ok, detail, 2, HOURLY_MAX_AGE_S, now))

    # a dump is listed once: the verdict is kept until a newer dump replaces it
    state_path = output / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    image = config.get("restoreImage", "postgres:17")
    for directory in sorted(p for p in Path(config.get("postgresDir", "/var/backups/postgres")).iterdir() if p.is_dir()):
        found = dumps(directory, config.get("pattern", "*.dump"))
        if not found:
            write(output, result(f"db/{directory.name}", False, f"no dumps in {directory}", 2, HOURLY_MAX_AGE_S, now))
            continue
        newest, key = found[-1], f"{found[-1]}:{found[-1].stat().st_mtime}"
        if key not in state.get("listed", {}):
            state.setdefault("listed", {})[key] = readable(image, newest)
        is_readable, error = state["listed"][key]
        ok, detail = judge_dump(newest.name, (now - newest.stat().st_mtime) / 3600, newest.stat().st_size,
                                [p.stat().st_size for p in found[:-1]], is_readable, error, config.get("maxDumpAgeH", 26))
        write(output, result(f"db/{directory.name}", ok, detail, 2, HOURLY_MAX_AGE_S, now))
    state["listed"] = dict(list(state.get("listed", {}).items())[-200:])

    st = os.statvfs(config.get("disk", "/"))
    total, used = st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bavail) * st.f_frsize
    history = [h for h in state.get("disk", []) if h[0] != date.today().toordinal()] + [[date.today().toordinal(), used, total]]
    state["disk"] = history[-60:]
    ok, tier, detail = judge_forecast(state["disk"])
    write(output, result("host/disk-forecast", ok, detail, tier, HOURLY_MAX_AGE_S, now))
    state_path.write_text(json.dumps(state), encoding="utf-8")


def weekly_restore(config: dict, output: Path, now: float) -> None:
    image = config.get("restoreImage", "postgres:17")
    for directory in sorted(p for p in Path(config.get("postgresDir", "/var/backups/postgres")).iterdir() if p.is_dir()):
        found = dumps(directory, config.get("pattern", "*.dump"))
        ok, detail = restore(image, directory.name, found[-1]) if found else (False, f"no dumps in {directory}")
        # tier 2: a backup that does not restore hurts nobody today, so it is work to schedule, not a page
        write(output, result(f"db/{directory.name}-restore", ok, detail, 2, RESTORE_MAX_AGE_S, now))


def main(command: str) -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    output = Path(config.get("output", "/var/lib/daedalus-checks"))
    (hourly if command == "hourly" else weekly_restore)(config, output, time.time())
    return 0


if __name__ == "__main__":
    if sys.argv[1:] not in (["hourly"], ["restore"]):
        sys.exit("usage: daedalus_checks.py hourly|restore")
    sys.exit(main(sys.argv[1]))
