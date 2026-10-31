"""checks/daedalus_checks.py: the judgement and the files it leaves for the agent. psql and docker are not run here."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from adapter import checks_source

_spec = importlib.util.spec_from_file_location("daedalus_checks", Path(__file__).resolve().parents[1] / "checks" / "daedalus_checks.py")
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)

DB = {"name": "ccb", "maxDumpAgeH": 26, "minTables": 1}


def test_a_fresh_full_restore_is_ok():
    ok, detail = checks.judge_restore(DB, 3, 0, 0, 42, 18_000)
    assert ok and detail == "restored: 42 tables, 18000 rows, dump 3 h old"


def test_an_old_or_empty_backup_is_not_a_backup():
    ok, detail = checks.judge_restore(DB, 50, 0, 0, 42, 18_000)
    assert not ok and detail.startswith("newest dump is 50 h old: backups stopped")
    assert not checks.judge_restore(DB, 3, 0, 0, 42, 0)[0]
    assert not checks.judge_restore(DB, 3, 1, 5, 0, 0)[0]


def test_errors_from_cloud_only_extensions_do_not_fail_a_restore_that_brought_the_data_back():
    ok, detail = checks.judge_restore(DB, 3, 1, 2, 42, 18_000)
    assert ok and detail.endswith("2 restore errors ignored")


def test_newest_dump_is_picked_by_time(tmp_path):
    old, new = tmp_path / "CCB_20261015_100028.dump", tmp_path / "CCB_20261016_100028.dump"
    for i, path in enumerate((old, new)):
        path.write_text("x")
        os.utime(path, (1_000 + i, 1_000 + i))
    (tmp_path / "notes.txt").write_text("x")
    assert checks.latest_dump(tmp_path, "*.dump") == new


def test_the_agent_reads_what_the_script_writes(tmp_path):
    now = 1_793_400_000.0
    checks.write(tmp_path, checks.result("ccb", "database", False, "connection refused", 1, checks.PING_MAX_AGE_S, now))
    (target,) = checks_source.read(str(tmp_path), now + 60)
    assert (target.name, target.ok, target.tier, target.detail) == ("ccb/database", False, 1, "connection refused")
    assert [p.name for p in tmp_path.iterdir()] == ["ccb-database.json"]       # no temporary file left behind
