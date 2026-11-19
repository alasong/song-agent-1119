"""通用任务执行器：读任务包（JSON），交给 daemon 跑。

任务包格式（放在 runs/<任务>/task.json）：
{
  "spec": "给模型的任务书",
  "target_file": "runs/<任务>/xxx.md",
  "tests": ["tests.test_xxx"],
  "fence_lang": "markdown",
  "max_tokens": 8000,
  "disable_thinking": true
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="任务包 JSON 路径")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    task_path = Path(args.task)
    task = json.loads(task_path.read_text(encoding="utf-8"))
    out_dir = task_path.parent

    cfg = DaemonConfig(
        spec=task["spec"],
        target_file=task["target_file"],
        tests=task["tests"],
        max_rounds=args.rounds,
        patience=2,
        fence_lang=task.get("fence_lang", "markdown"),
        context_files=task.get("context_files", []),
    )
    extra = {"thinking": {"type": "disabled"}} if task.get("disable_thinking") else None
    max_tokens = int(task.get("max_tokens", 8000))
    llm = lambda messages: complete(messages, model=args.model, max_tokens=max_tokens, extra=extra)

    summary = Daemon(Ledger(out_dir / "ledger.jsonl"), llm, cfg).run()
    summary.update({"model": args.model, "task_file": str(task_path)})
    (out_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["green_at_round"] else 1


if __name__ == "__main__":
    raise SystemExit(main())