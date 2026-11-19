"""单 agent 路径：一个执行者跑到判据通过就交，不组队。

抽出来单独成型，是因为「先一个人干」必须是默认路径——
组织只有在单 agent 判不过、或任务本身要求分工/独立复核时才上场。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger
from xm.paths import runs_root



def run_single(task_dir: Path, llm, budget_tokens: int = 200_000,
               run_root: Path | None = None, rounds: int = 3) -> dict:
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    root = run_root or (runs_root() / "single")
    run_dir = root / f"single-{time.strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / task["target_name"]
    cfg = DaemonConfig(
        spec=task["spec"], target_file=str(target), tests=[],
        artifacts_root=str(runs_root()),
        verify_cmd=[sys.executable, str(task_dir / task.get("check", "check.py")), str(target)],
        max_rounds=rounds, patience=2, fence_lang=task.get("fence_lang", "markdown"),
        budget_tokens=budget_tokens,
    )
    summary = Daemon(Ledger(run_dir / "ledger.jsonl"), llm, cfg).run()
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    return {
        "passed": bool(summary["green_at_round"]),
        "rounds": summary["rounds_used"],
        "chars": len(text),
        "artifact": str(target),
        "text": text,
        "run_dir": str(run_dir),
    }
