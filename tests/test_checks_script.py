"""checks/daedalus_checks.py: what it decides, and the files it leaves for the agent. systemctl and docker are not run here."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from adapter import checks_source

_spec = importlib.util.spec_from_file_location("daedalus_checks", Path(__file__).resolve().parents[1] / "checks" / "daedalus_checks.py")
checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checks)

NOW = 1_793_400_000.0
VCB = [1_516_316_417, 1_528_134_012, 1_525_080_218, 1_529_178_165, 1_541_365_777, 1_554_663_895, 1_546_702_024]


# ------------------------------------------------------------------ dumps ---

def test_a_fresh_readable_dump_of_the_usual_size_is_ok():
    ok, detail = checks.judge_dump("VCB_20261102_100057.dump", 4, 1_546_704_106, VCB, True, "", 26)
    assert ok and detail == "VCB_20261102_100057.dump: 1.55 GB, 4 h old"


def test_backups_that_stopped_are_named_as_such():
    ok, detail = checks.judge_dump("CCB_20261016_100028.dump", 400, 1_000_000, [1_000_000], True, "", 26)
    assert not ok and detail.startswith("newest dump is 400 h old: backups stopped")


def test_an_unreadable_or_shrunken_dump_is_a_failure():
    assert checks.judge_dump("x.dump", 4, 1_500_000_000, VCB, False, "unexpected end of file", 26) == \
        (False, "x.dump is unreadable: unexpected end of file")
    ok, detail = checks.judge_dump("x.dump", 4, 11_899, VCB, True, "", 26)
    assert not ok and "data is missing" in detail


def test_growth_is_news_not_a_fault():
    """ATLANTIC went from an empty schema (11 899 bytes) to 6.6 MB when the project went live."""
    ok, detail = checks.judge_dump("ATLANTIC_20261101_100022.dump", 4, 6_651_225, [11_899] * 7, True, "", 26)
    assert ok and detail.endswith("559× the usual 0.0 MB")


# ------------------------------------------------------------------- jobs ---

FAILED = {"Result": "exit-code", "ExecMainStatus": "1", "ExecMainExitTimestampMonotonic": "123",
          "ExecMainExitTimestamp_unix": str(int(NOW - 3 * 3600))}


def test_a_failed_job_says_why():
    ok, detail = checks.judge_job(FAILED, "Host key verification failed.", NOW)
    assert not ok and detail == "last run 3 h ago failed (exit 1): Host key verification failed."


def test_a_job_that_succeeded_or_never_ran_is_ok():
    assert checks.judge_job({**FAILED, "Result": "success"}, None, NOW) == (True, "last run 3 h ago: ok")
    assert checks.judge_job({"ExecMainExitTimestampMonotonic": "0"}, None, NOW)[0]


# ------------------------------------------------------------------- disk ---

def _history(days, used_start, per_day, total=77e9):
    return [[d, used_start + d * per_day, total] for d in range(days)]


def test_the_disk_forecast_needs_a_week_of_samples_first():
    assert checks.judge_forecast(_history(3, 31e9, 1e9)) == (True, 2, "collecting history: 3 of 7 days")


@pytest.mark.parametrize(("per_day", "ok", "tier"), [(0.2e9, True, 2), (4e9, False, 2), (7e9, False, 1)])
def test_days_until_full_decide_the_tier(per_day, ok, tier):
    """77 GB disk, 31 GB on day 0, a week of samples: 0.2 GB a day leaves months, 4 GB under a week, 7 GB under a day."""
    history = _history(7, 31e9, per_day)
    assert checks.judge_forecast(history)[:2] == (ok, tier)


def test_a_disk_that_is_not_growing_has_no_forecast():
    assert checks.judge_forecast(_history(10, 31e9, -0.1e9)) == (True, 2, "not filling up over the last 30 days")


# --------------------------------------------------------------- restores ---

def test_restore_judgement():
    assert checks.judge_restore("VCB.dump", 0, 0, 42, 18_000_000, 600) == (True, "VCB.dump restores: 42 tables, 18000000 rows in 10 min")
    assert not checks.judge_restore("ATLANTIC.dump", 0, 0, 3, 0, 5)[0]           # an empty schema restores to nothing
    ok, detail = checks.judge_restore("CCB.dump", 1, 2, 30, 5000, 60)            # extensions the cloud has and we do not
    assert ok and detail.endswith("2 restore errors ignored")


# ---------------------------------------------------------------- plumbing ---

def test_dumps_are_ordered_by_time(tmp_path):
    for i, name in enumerate(("CCB_2.dump", "CCB_1.dump")):
        (tmp_path / name).write_text("x")
        os.utime(tmp_path / name, (1_000 + i, 1_000 + i))
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in checks.dumps(tmp_path, "*.dump")] == ["CCB_2.dump", "CCB_1.dump"]


def test_the_agent_reads_what_the_script_writes(tmp_path):
    checks.write(tmp_path, checks.result("job/file-backup", False, "Host key verification failed.", 2, checks.HOURLY_MAX_AGE_S, NOW))
    (target,) = checks_source.read(str(tmp_path), NOW + 60)
    assert (target.name, target.ok, target.tier) == ("job/file-backup", False, 2)
    assert [p.name for p in tmp_path.iterdir()] == ["job-file-backup.json"]       # no temporary file left behind
    assert json.loads((tmp_path / "job-file-backup.json").read_text())["maxAgeS"] == 3 * 3600
