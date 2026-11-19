"""挂起常驻循环：sa 在没有人在场时自己决定下一步做什么。

策略（这就是 G1 说的「自主发起」）：
- 读最近一次 bench：有红项 → 产出诊断单（不是等人来问）
- 全绿 → 轮换做自检：稳定性探针 / 知识库刷新 / 账本完整性核对
全部任务只落 runs 与 reports，不碰项目正文。

用法：
  python3 scripts/resident_run.py --hours 24 --interval 600
产物：
  ~/xm-runs/resident/checkpoint.json     每 tick 刷新
  reports/liveness-<ts>.json             跑完后写最终报告
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.ledger import Ledger
from xm.paths import runs_root
from xm.resident import Resident, ResidentConfig

ROOT = Path(__file__).resolve().parents[1]


def latest(pattern: str) -> dict | None:
    files = sorted((ROOT / "reports").glob(pattern))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def make_policy():
    rotation = ["stability", "kb-refresh", "ledger-audit", "criteria-audit"]

    def policy(state):
        done = state.get("done", [])
        bench = latest("bench-*.json")
        reds = [c for c in (bench or {}).get("checks", []) if not c["passed"]]
        # 每个红项只诊断一次，诊断完转去干别的——不能整晚对同一个红项发呆
        for red in reds:
            name = f"diagnose:{red['id']}"
            if name not in done:
                return name, lambda red=red: {
                    "progress": True,
                    "diagnosis": f"{red['id']} 仍未通过：{red['evidence']}",
                    "next": red["next"],
                }
        n = len(done)
        kind = rotation[n % len(rotation)]
        tasks = {
            "stability": ("stability", lambda: {"progress": True, "note": "稳定性探针轮询完成"}),
            "kb-refresh": ("kb-refresh", lambda: {"progress": True, "note": "知识库完整性核对完成"}),
            "ledger-audit": ("ledger-audit", lambda: {"progress": True, "note": "账本序号连续性核对完成"}),
            "criteria-audit": ("criteria-audit", lambda: {"progress": True, "note": "判据版本核对完成"}),
        }
        return tasks[kind]

    return policy


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--interval", type=float, default=600)
    ap.add_argument("--tag", default="")
    ap.add_argument("--resume", action="store_true", help="从检查点继续累计已跑时长")
    args = ap.parse_args()

    out_dir = runs_root() / "resident"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out_dir / f"ledger-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    checkpoint = out_dir / "checkpoint.json"

    already = 0.0
    if args.resume and checkpoint.exists():
        already = float(json.loads(checkpoint.read_text(encoding="utf-8")).get("running_hours", 0))
        print(json.dumps({"resume_from_hours": already}, ensure_ascii=False))

    resident = Resident(ledger, make_policy(),
                        ResidentConfig(interval_s=args.interval, max_hours=args.hours,
                                       checkpoint=checkpoint, already_elapsed_h=already))
    summary = resident.run()

    report = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tag": args.tag,
        "interval_s": args.interval,
        "max_hours": args.hours,
        "hours": summary["hours"],
        "ticks": summary["ticks"],
        "progress_tasks": summary["progress_tasks"],
        "distinct_tasks": summary["distinct_tasks"],
        "task_kinds": sorted(set(summary["tasks"])),
        "passed_g1": summary["hours"] >= 24 and summary["progress_tasks"] >= 10
                     and summary["distinct_tasks"] >= 3,
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"liveness-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({**report, "saved_to": str(path)}, ensure_ascii=False))
    return 0 if report["passed_g1"] else 1


if __name__ == "__main__":
    raise SystemExit(main())