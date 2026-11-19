"""用 sa（组织级）跑一个任务：目标 + 任务目录（含 task.json / check.py）。

用法：
  python3 scripts/sa_run.py --goal "如何解决 AI 漂移问题" --task ~/xm-runs/2026-11-19-drift
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.llm import complete
from xm.sa_task import run
from xm.paths import runs_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--task", required=True, help="任务目录（含 task.json / check.py）")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-roles", type=int, default=None, help="收缩编制：最多几个角色（保留 verifier）")
    ap.add_argument("--max-stages", type=int, default=None, help="收缩流程：最多几个阶段")
    args = ap.parse_args()

    task_dir = Path(args.task).expanduser().resolve()
    if not (task_dir / "task.json").exists():
        print(json.dumps({"error": f"{task_dir} 里没有 task.json"}, ensure_ascii=False))
        return 2

    llm = lambda messages, max_tokens=2000: complete(
        messages, model=args.model, max_tokens=max_tokens,
        extra={"thinking": {"type": "disabled"}},
    )
    report = run(args.goal, task_dir, llm, rounds=args.rounds,
                 max_roles=args.max_roles, max_stages=args.max_stages)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())