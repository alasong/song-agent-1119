"""按一份 OrgPlan 派活：sa 把编制真正派出去。

用法：python3 scripts/dispatch_org.py --plan ~/xm-runs/org/<ts>.json
记录写到 reports/scheduler-<ts>.json，供 bench 的 G2 判据读取。
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
from xm.scheduler import Scheduler

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--llm", action="store_true", help="用真模型扮演角色（默认 stub）")
    ap.add_argument("--roles", type=int, default=0, help="只用前 N 个角色（0=全部）")
    ap.add_argument("--stages", type=int, default=0, help="只用前 N 个阶段（0=全部）")
    args = ap.parse_args()

    plan_path = Path(args.plan).expanduser().resolve()
    out_dir = runs_root() / "dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out_dir / f"ledger-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")

    scheduler = Scheduler.from_plan_file(plan_path, ledger)
    plan = scheduler.plan
    if args.roles:
        plan["roles"] = plan["roles"][:args.roles]
    if args.stages:
        plan["process"] = plan["process"][:args.stages]

    worker = None
    worker_mode = "stub"
    if args.llm:
        from xm.worker import RoleWorker
        from xm.llm import complete
        llm = lambda messages: complete(messages, model="deepseek-flash", max_tokens=700,
                                        extra={"thinking": {"type": "disabled"}})
        from xm.worker import VerifierWorker
        base_worker = RoleWorker(llm)
        verifier_worker = VerifierWorker(llm)
        all_artifacts = []

        def worker(role, stage, upstream):
            w = verifier_worker if role.get("kind") == "verifier" else base_worker
            artifact = w(role, stage, upstream)
            all_artifacts.append(artifact)
            return artifact
        worker_mode = "llm"

    stats = scheduler.run(plan, worker=worker)
    stats["worker_mode"] = worker_mode
    if worker is not None:
        artifacts = all_artifacts
        verdicts = [a for a in artifacts if "verdict" in a]
        stats["verdicts"] = len(verdicts)
        # reworks 直接用调度器返回的计数（返工产物由调度器内部生成，不经过 worker 收集口）
        stats["verdict_pass"] = sum(1 for a in verdicts if a["verdict"] == "pass")
        stats["verdict_reject"] = sum(1 for a in verdicts if a["verdict"] == "reject")
        stats["sample_artifact"] = artifacts[-1]["content"][:120] if artifacts else ""

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plan": str(plan_path),
        **stats,
        "distinct_role_names": sorted({d.role for d in scheduler.dispatch_log}),
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"scheduler-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if stats["distinct_roles"] >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())