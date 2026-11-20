#!/usr/bin/env python3
"""S5 演示：同条件第二次造编制，模型调用 0 次，账本记 plan_reused。

跑法：python3 scripts/demo_plan_reuse.py
不出网；tokens 的等价读数是「模型调用次数」——plan 这一步的 token 就是这些调用花的。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.ledger import Ledger  # noqa: E402
from sa2.forge import org as fo  # noqa: E402
from sa2.memory.plans import PlanStore  # noqa: E402

ORG = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆解任务", "criteria": "有子任务", "budget": 100},
        {"name": "执行", "kind": "executor", "duty": "写正文", "criteria": "章节齐全", "budget": 200},
        {"name": "验证", "kind": "verifier", "duty": "独立判", "criteria": "有结论", "budget": 50},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["c1"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["c1", "c2"]},
    ],
}, ensure_ascii=False)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = PlanStore(root / "plans.json")
        ledger = Ledger(root / "ledger.jsonl")
        calls: list[str] = []

        def llm(messages, max_tokens=None):
            calls.append("call")
            return ORG

        print("① 第一次造编制（同目标、同预算、同判据）")
        first = fo.plan_org("写一篇稿", llm, budget_cap=10_000,
                            criteria=("c1", "c2"), store=store, ledger=ledger)
        print(f"   模型调用 {len(calls)} 次；编制 {len(first.roles)} 角色 / {len(first.stages)} 阶段")

        print("② 同条件第二次（应命中编制库）")
        second = fo.plan_org("写一篇稿", llm, budget_cap=10_000,
                             criteria=("c1", "c2"), store=store, ledger=ledger)
        print(f"   模型调用仍是 {len(calls)} 次；账本 plan_reused={ledger.count('plan_reused')}")
        print(f"   角色一致：{[r.name for r in second.roles] == [r.name for r in first.roles]}")

        print("③ 反例：预算换成 9000，必须重新造")
        fo.plan_org("写一篇稿", llm, budget_cap=9_000,
                    criteria=("c1", "c2"), store=store, ledger=ledger)
        print(f"   模型调用 {len(calls)} 次（=2 说明预算进了复合键）")

        print("④ 反例：判据只是顺序不同，不该重新造")
        fo.plan_org("写一篇稿", llm, budget_cap=10_000,
                    criteria=("c2", "c1"), store=store, ledger=ledger)
        ok = len(calls) == 2 and ledger.count("plan_reused") == 2
        print(f"   模型调用 {len(calls)} 次（仍 2）；plan_reused={ledger.count('plan_reused')}")
        print(f"⑤ 判定：{'过' if ok else '红'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())