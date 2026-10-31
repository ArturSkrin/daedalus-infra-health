"""Outside checks (database ping, backup restore) reported as JSON files and read as targets."""
from __future__ import annotations

import json

from adapter import checks_source

NOW = 1_793_400_000.0


def _write(tmp_path, file, **item):
    (tmp_path / f"{file}.json").write_text(json.dumps(item))


def test_fresh_results_become_targets_with_their_tier(tmp_path):
    _write(tmp_path, "ccb-neon", name="ccb/neon", ok=True, detail="SELECT 1 in 84 ms", tier=1, checkedAtUnix=NOW - 60, maxAgeS=900)
    _write(tmp_path, "ccb-backup", name="ccb/backup", ok=False, detail="restore failed", tier=2, checkedAtUnix=NOW - 3600, maxAgeS=93600)
    found = {c.name: c for c in checks_source.read(str(tmp_path), NOW)}
    assert (found["ccb/neon"].ok, found["ccb/neon"].tier, found["ccb/neon"].detail) == (True, 1, "SELECT 1 in 84 ms")
    assert (found["ccb/backup"].ok, found["ccb/backup"].tier) == (False, 2)


def test_a_check_that_stopped_running_is_a_failure_not_its_last_ok(tmp_path):
    _write(tmp_path, "ccb-neon", name="ccb/neon", ok=True, tier=1, checkedAtUnix=NOW - 1800, maxAgeS=900)
    (neon,) = checks_source.read(str(tmp_path), NOW)
    assert not neon.ok
    assert neon.detail == "no result for 30 min: the check itself is not running"


def test_broken_files_are_shown_and_a_missing_directory_is_nothing(tmp_path):
    (tmp_path / "half.json").write_text("{\"name\": \"x\"")
    (broken,) = checks_source.read(str(tmp_path), NOW)
    assert (broken.name, broken.ok) == ("check/half", False)
    assert checks_source.read(str(tmp_path / "missing"), NOW) == []
