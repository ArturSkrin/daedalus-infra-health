#!/usr/bin/env python3
"""Database checks for Daedalus, run by systemd timers on the backup server. Standard library only.

    daedalus_checks.py ping      SELECT 1 on every database, as a role that can read nothing   (every 5 min)
    daedalus_checks.py restore   restore the newest dump into a throwaway postgres, count what came back (daily)

Each check writes <output>/<database>-<check>.json, which the Daedalus agent on this host reads as a target
(adapter/checks_source.py). Config: /etc/daedalus-checks/config.json (root only, it holds connection strings):

    {"output": "/var/lib/daedalus-checks", "restoreImage": "postgres:17",
     "databases": [{"name": "ccb", "url": "postgresql://daedalus_check:...@host/db?sslmode=require",
                    "backups": "/var/backups/postgres/CCB", "pattern": "*.dump", "maxDumpAgeH": 26, "minTables": 1}]}
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

CONFIG = Path("/etc/daedalus-checks/config.json")
PING_MAX_AGE_S = 15 * 60            # three missed 5-minute runs: the timer itself is broken
RESTORE_MAX_AGE_S = 30 * 3600       # daily, with room for a slow run
COUNT_ROWS = ("SELECT count(*), coalesce(sum((xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I',"
              " table_schema, table_name), false, true, '')))[1]::text::bigint), 0) FROM information_schema.tables"
              " WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')")


def result(name: str, check: str, ok: bool, detail: str, tier: int, max_age_s: int, now: float) -> dict:
    return {"name": f"{name}/{check}", "ok": ok, "detail": detail, "tier": tier, "checkedAtUnix": now, "maxAgeS": max_age_s}


def write(output: Path, item: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    path = output / (item["name"].replace("/", "-") + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(item), encoding="utf-8")
    temporary.replace(path)                     # the agent never reads half a file


def latest_dump(directory: Path, pattern: str) -> Path | None:
    dumps = [p for p in directory.glob(pattern) if p.is_file()]
    return max(dumps, key=lambda p: p.stat().st_mtime) if dumps else None


def judge_restore(db: dict, dump_age_h: float, restore_rc: int, errors: int, tables: int, rows: int) -> tuple[bool, str]:
    """Restored is not enough: an empty or week-old backup restores perfectly and saves nothing."""
    facts = f"{tables} tables, {rows} rows, dump {dump_age_h:.0f} h old" + (f", {errors} restore errors ignored" if errors else "")
    if dump_age_h > db.get("maxDumpAgeH", 26):
        return False, f"newest dump is {dump_age_h:.0f} h old: backups stopped ({facts})"
    if tables < db.get("minTables", 1) or rows == 0:
        return False, f"the dump restores to almost nothing ({facts})"
    if restore_rc != 0 and tables == 0:
        return False, f"pg_restore failed ({facts})"
    return True, f"restored: {facts}"


def _run(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def ping(db: dict) -> tuple[bool, str]:
    started = time.monotonic()
    try:
        done = _run("psql", db["url"], "-tAc", "select 1", timeout=20)
    except subprocess.TimeoutExpired:
        return False, "no answer in 20 s"
    if done.returncode != 0 or done.stdout.strip() != "1":
        return False, (done.stderr.strip().splitlines() or ["psql failed"])[-1][:200]
    return True, f"SELECT 1 in {(time.monotonic() - started) * 1000:.0f} ms"


def restore(db: dict, image: str, now: float) -> tuple[bool, str]:
    dump = latest_dump(Path(db["backups"]), db.get("pattern", "*.dump"))
    if dump is None:
        return False, f"no dumps in {db['backups']}"
    age_h = (now - dump.stat().st_mtime) / 3600
    container = f"daedalus-restore-{db['name']}"
    _run("docker", "rm", "-f", container)
    try:
        # no network, no published port, trust auth inside: the container exists only for this run
        started = _run("docker", "run", "-d", "--rm", "--name", container, "--network", "none",
                       "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image)
        if started.returncode != 0:
            return False, f"cannot start {image}: {started.stderr.strip()[:200]}"
        for _ in range(60):
            if _run("docker", "exec", container, "pg_isready", "-U", "postgres", "-q").returncode == 0:
                break
            time.sleep(1)
        _run("docker", "cp", str(dump), f"{container}:/tmp/restore.dump")
        restored = _run("docker", "exec", container, "pg_restore", "-U", "postgres", "-d", "postgres",
                        "--no-owner", "--no-acl", "/tmp/restore.dump", timeout=3600)
        errors = restored.stderr.count("error:")
        counted = _run("docker", "exec", container, "psql", "-U", "postgres", "-tAF", " ", "-c", COUNT_ROWS)
        tables, rows = (int(x) for x in (counted.stdout.split() or ["0", "0"])[:2])
        ok, detail = judge_restore(db, age_h, restored.returncode, errors, tables, rows)
        return ok, f"{dump.name}: {detail}"
    finally:
        _run("docker", "rm", "-f", container)


def main(command: str) -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    output = Path(config.get("output", "/var/lib/daedalus-checks"))
    for db in config["databases"]:
        now = time.time()
        if command == "ping" and db.get("url"):
            ok, detail = ping(db)
            write(output, result(db["name"], "database", ok, detail, 1, PING_MAX_AGE_S, now))   # users feel this at once
        elif command == "restore" and db.get("backups"):
            ok, detail = restore(db, config.get("restoreImage", "postgres:17"), now)
            write(output, result(db["name"], "backup", ok, detail, 2, RESTORE_MAX_AGE_S, now))  # nobody feels it until the day it is needed
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("ping", "restore"):
        sys.exit("usage: daedalus_checks.py ping|restore")
    sys.exit(main(sys.argv[1]))
