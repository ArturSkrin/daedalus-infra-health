"""Export every scenario's view model as static JSON.

Static hosting (GitHub Pages) has no backend. The frontend first asks /api and
falls back to these files, so the hosted prototype shows exactly what the API
would serve. Run before `npm run build`:

    python -m backend.export_views frontend/public/views
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.engine import verdict
from backend.presentation import build_view
from backend.repository import list_scenarios, load_scenario


def main(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for item in list_scenarios():
        data = load_scenario(item["id"])
        result = verdict(data)
        view = build_view(data, result, mode="demo")
        (out / f"{item['id']}.json").write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        index.append({**item, "actual": result["verdict"], "passed": view["validation"]["passed"]})
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"exported {len(index)} views to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "frontend/public/views"))
