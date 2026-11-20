#!/usr/bin/env python3
"""集成检查：一条命令跑完单测、两次演练、全部演示。

  python3 scripts/integration_check.py

任一步非零退出即整体判红。这是 P0–P5 收口时的可复跑口径。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    ("全量单测", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"]),
    ("入口自检 sa2_live --help", [sys.executable, "scripts/sa2_live.py", "--help"]),
    ("演练：角色死亡 + 进程硬杀", [sys.executable, "scripts/drill_kill.py"]),
    ("演练：kill -9 worker", [sys.executable, "scripts/drill_kill.py", "--kill-worker"]),
    ("演示：角色档案", [sys.executable, "scripts/demo_role_profile.py"]),
    ("演示：接管", [sys.executable, "scripts/demo_takeover.py"]),
    ("演示：派活经 worker", [sys.executable, "scripts/demo_pool_run.py"]),
    ("演示：编制复用", [sys.executable, "scripts/demo_plan_reuse.py"]),
    ("演示：指标 + 外环 + 采纳", [sys.executable, "scripts/demo_metrics_outer.py"]),
    ("演示：资源账本", [sys.executable, "scripts/demo_resource.py"]),
    ("演示：状态机 harness", [sys.executable, "scripts/demo_harness.py"]),
]


def main() -> int:
    failed: list[str] = []
    for index, (name, cmd) in enumerate(STEPS, 1):
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        mark = "过" if result.returncode == 0 else "红"
        print(f"{index:02d} {name:<28} {mark}  rc={result.returncode}")
        if result.returncode != 0:
            failed.append(name)
            tail = (result.stdout + result.stderr).strip().splitlines()[-8:]
            for line in tail:
                print(f"    | {line}")
    print(f"\n集成检查：{len(STEPS) - len(failed)}/{len(STEPS)} 过"
          + (f"；红：{failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())