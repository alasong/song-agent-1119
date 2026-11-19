"""通用任务执行器：任务包放在项目之外的 runs 根下，产物与判据都跟着任务走。

任务包格式（runs/<任务>/task.json）：
{
  "spec": "给模型的任务书",
  "target_name": "analysis.md",
  "fence_lang": "markdown",
  "max_tokens": 8000,
  "disable_thinking": true,
  "check": "check.py"
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger
from xm.llm import complete
from xm.paths import runs_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="任务包 JSON 路径（在 runs 根下）")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    task_path = Path(args.task).expanduser().resolve()
    root = runs_root()
    if not task_path.is_relative_to(root):
        print(f"拒绝执行：任务包必须放在 {root} 下，不在项目目录里跑一次性任务")
        return 2

    task = json.loads(task_path.read_text(encoding="utf-8"))
    out_dir = task_path.parent
    target = out_dir / task["target_name"]
    check = out_dir / task.get("check", "check.py")

    cfg = DaemonConfig(
        spec=task["spec"],
        target_file=str(target),
        tests=[],
        artifacts_root=str(root),
        verify_cmd=[sys.executable, str(check), str(target)],
        max_rounds=args.rounds,
        patience=2,
        fence_lang=task.get("fence_lang", "markdown"),
    )
    extra = {"thinking": {"type": "disabled"}} if task.get("disable_thinking") else None
    llm = lambda messages: complete(
        messages, model=args.model, max_tokens=int(task.get("max_tokens", 8000)), extra=extra
    )

    summary = Daemon(Ledger(out_dir / "ledger.jsonl"), llm, cfg).run()
    summary.update({"model": args.model, "task_file": str(task_path), "target": str(target)})
    (out_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["green_at_round"] else 1


if __name__ == "__main__":
    raise SystemExit(main())