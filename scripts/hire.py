"""sa 的 Super 入口（组队）：给一个目标，让它自己组队、定流程、分预算。

产物写到项目之外（~/xm-runs/org/），不污染仓库。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.hiring import plan_org
from xm.llm import complete
from xm.paths import runs_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--budget-cap", type=int, default=200_000)
    args = ap.parse_args()

    llm = lambda messages: complete(
        messages, model=args.model, max_tokens=2000,
        extra={"thinking": {"type": "disabled"}},
    )
    plan = plan_org(args.goal, llm, budget_cap=args.budget_cap)

    out = runs_root() / "org"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({
        "goal": plan.goal,
        "roles": [asdict(r) for r in plan.roles],
        "process": plan.process,
        "total_budget": plan.total_budget,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "goal": plan.goal,
        "total_budget": plan.total_budget,
        "process": plan.process,
        "roles": [{"name": r.name, "kind": r.kind, "criteria": r.criteria, "budget": r.budget}
                  for r in plan.roles],
        "saved_to": str(path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())