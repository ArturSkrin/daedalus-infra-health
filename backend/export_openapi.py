"""Write the API contract to frontend/openapi.json.

The frontend types are generated from this file (`npm run gen:types`), and CI
fails when the committed copy differs from what the code produces.

    python -m backend.export_openapi
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.main import app


def main(out: str) -> int:
    Path(out).write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "frontend/openapi.json"))
