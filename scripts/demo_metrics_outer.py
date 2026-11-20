#!/usr/bin/env python3
"""S7 演示：从历史 run 复算健康指标 → 外环提一条候选 → 小预算试 → 决定落盘。

跑法：python3 scripts/demo_metrics_outer.py
不出网：实验用注入的假 runner 推进，证明的是「闭环能转、决定会落盘」。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.metrics import from_run  # noqa: E402
from sa2.loop.outer import propose, run  # noqa: E402


def _ledger_lines() -> str:
    events = [
        {"kind": "dispatch", "actor": "规划", "payload": {"chars": 0}},
        {"kind": "dispatch", "actor": "执行", "payload": {"chars": 40}},
        {"kind": "stage_ok", "actor": "起草", "payload": {"attempt": 1}},
        {"kind": "dispatch", "actor": "执行", "payload": {"chars": 60}},
        {"kind": "stage_ok", "actor": "成稿", "payload": {"attempt": 1}},
        {"kind": "takeover", "actor": "执行", "payload": {"from": "执行", "to": "执行"}},
        {"kind": "delivery", "actor": "gate", "payload": {"passed": True}},
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "ledger.jsonl").write_text(_ledger_lines(), encoding="utf-8")
        (run_dir / "readings.json").write_text(json.dumps(
            {"chars": 100, "budget": {"spent": 500}}), encoding="utf-8")

        print("① 从历史 run 复算指标（不重跑模型）")
        m = from_run(run_dir)
        for key in ("validation_pass_rate", "takeover_rate",
                    "communication_efficiency", "resource_efficiency"):
            print(f"   {key} = {m[key]}")
        print(f"   flags = {m['flags']}")
        print(f"   unavailable = {m['unavailable']}")

        print("② 外环按规则提一条候选")
        candidates = propose(m)
        experiment = candidates[0]
        print(f"   {experiment['hypothesis']}")
        print(f"   指标={experiment['metric']} baseline={experiment['baseline']} "
              f"expect={experiment['expect']} budget={experiment['budget']}")

        path = root / "outer.jsonl"

        def simulated(experiment: dict, delta: float) -> dict:
            value = (experiment["baseline"] + delta if experiment["expect"] == "up"
                     else experiment["baseline"] - delta)
            return {experiment["metric"]: value}

        print("③ 小预算试一次（假 runner：指标按预期方向移动 → 采纳）")
        adopted = run(experiment, lambda e: simulated(e, 0.2), budget_cap=20_000, path=path)
        print(f"   status={adopted['status']} after={adopted.get('after')} why={adopted['why']}")

        print("④ 同样的候选再试一次（指标没动 → 拒绝）")
        rejected = run(experiment, lambda e: simulated(e, 0.0), budget_cap=20_000, path=path)
        print(f"   status={rejected['status']} after={rejected.get('after')} why={rejected['why']}")

        print("⑤ 超预算的实验：refused，一次都不跑")
        over = dict(experiment, budget=10 ** 6)
        refused = run(over, lambda e: {}, budget_cap=20_000, path=None)
        print(f"   status={refused['status']} why={refused['why']}")

        lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        ok = (adopted["status"] == "adopted" and rejected["status"] == "rejected"
              and refused["status"] == "refused" and len(lines) == 2)
        print(f"⑥ 决定落盘 {len(lines)} 条；判定：{'过' if ok else '红'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())