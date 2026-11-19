"""稳定性探针：同一个目标连续组队 N 次，看编制会不会漂。

判据（见 docs/ACCEPTANCE.md G5）：N=3，角色类型集合的两两 Jaccard 均值 ≥ 2/3。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.hiring import plan_org
from xm.llm import complete

ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 2 / 3


def jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", default="给一个中型团队的内部工具做一套可回归的自动化验收")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--model", default="deepseek-flash")
    args = ap.parse_args()

    llm = lambda messages: complete(
        messages, model=args.model, max_tokens=2000,
        extra={"thinking": {"type": "disabled"}},
    )

    runs = []
    for _ in range(args.n):
        plan = plan_org(args.goal, llm)
        runs.append({
            "kinds": sorted({r.kind for r in plan.roles}),
            "names": [r.name for r in plan.roles],
            "total_budget": plan.total_budget,
        })

    scores = [jaccard(set(a["kinds"]), set(b["kinds"]))
              for a, b in combinations(runs, 2)]
    avg = round(sum(scores) / len(scores), 4) if scores else 0.0

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "goal": args.goal,
        "n": args.n,
        "pairwise_jaccard": [round(s, 4) for s in scores],
        "score": avg,
        "threshold": THRESHOLD,
        "passed": avg >= THRESHOLD,
        "runs": runs,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"stability-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "n": record["n"], "pairwise_jaccard": record["pairwise_jaccard"],
        "score": avg, "threshold": THRESHOLD, "passed": record["passed"],
        "kinds_per_run": [r["kinds"] for r in runs], "saved_to": str(path),
    }, ensure_ascii=False, indent=2))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())