"""Results of checks that run outside the agent (a database ping, a backup restore), read from JSON files.

Any script can report this way: write <CHECKS_DIR>/<anything>.json with

    {"name": "ccb/neon", "ok": true, "detail": "SELECT 1 in 84 ms", "tier": 1,
     "checkedAtUnix": 1793400000, "maxAgeS": 900}

and it becomes a target like a container. A result older than maxAgeS is a failure: a check that stopped
running must not keep its last \"ok\" on the screen forever. Never raises.
"""
from __future__ import annotations

import json
from pathlib import Path

from adapter.docker_source import Container


def read(directory: str, now: float) -> list[Container]:
    found = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            name, tier = str(item.get("name") or f"check/{path.stem}"), int(item.get("tier", 2))
            age, max_age = now - float(item["checkedAtUnix"]), float(item.get("maxAgeS", 3600))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            found.append(Container(f"check/{path.stem}", 2, False, "the check result cannot be read", None))
            continue
        if age > max_age:
            found.append(Container(name, tier, False, f"no result for {int(age // 60)} min: the check itself is not running", None))
        else:
            found.append(Container(name, tier, bool(item.get("ok")), str(item.get("detail") or ""), None))
    return found
