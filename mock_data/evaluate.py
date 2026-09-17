from __future__ import annotations

import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from backend.engine import verdict


def main(
    argv: list[str],
) -> int:
    only = (
        argv[1]
        if len(argv) > 1
        else None
    )

    files = sorted(
        HERE.glob("s*.json")
    )

    selected = [
        path
        for path in files
        if (
            not only
            or path.name.startswith(
                only,
            )
        )
    ]

    failed = 0

    print(
        f"{'scenario':<26}"
        f"{'users':<12}"
        f"{'forecast':<12}"
        f"{'trust':<12}"
        f"{'day':<14}"
        f"{'verdict':<14}"
        "ok"
    )

    for path in selected:
        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        got = verdict(data)
        expected = data["expected"]

        ok = (
            got["verdict"]
            == expected["verdict"]
            and got["states"]
            == expected["states"]
        )

        if not ok:
            failed += 1

        states = got["states"]

        status = (
            "✓"
            if ok
            else (
                "✗ expected "
                + expected["verdict"]
                + " "
                + str(expected["states"])
            )
        )

        print(
            f"{data['scenario']:<26}"
            f"{states['users']:<12}"
            f"{states['forecast']:<12}"
            f"{states['trust']:<12}"
            f"{states['day']:<14}"
            f"{got['verdict']:<14}"
            f"{status}"
        )

        if only:
            print()
            print(
                json.dumps(
                    got["detail"],
                    ensure_ascii=False,
                    indent=2,
                )
            )

    if not only:
        print()
        print(
            f"{len(selected) - failed}/"
            f"{len(selected)} scenarios "
            "match metrics_spec.md"
        )

    return (
        1
        if failed
        else 0
    )


if __name__ == "__main__":
    sys.exit(
        main(sys.argv)
    )
