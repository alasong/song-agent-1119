#!/usr/bin/env python3
"""S9 演示：一轮 PDCA 的派活真的在 worker 进程里执行。

跑法：python3 scripts/demo_pool_run.py
假模型不出网；要证明的是「进程换了」，不是「模型多好」。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.gate import Declaration  # noqa: E402
from sa2.core.judge import Judge  # noqa: E402
from sa2.core.ledger import Ledger  # noqa: E402
from sa2.forge import criteria as fc  # noqa: E402
from sa2.forge import dims as fd  # noqa: E402
from sa2.forge import org as fo  # noqa: E402
from sa2.loop.pdca import PDCA  # noqa: E402
from sa2.loop.pool_producer import PoolProducer  # noqa: E402
from sa2.loop.workers import WorkerPool  # noqa: E402

ORG = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆", "criteria": "可验收", "budget": 10},
        {"name": "执行", "kind": "executor", "duty": "写", "criteria": "齐全", "budget": 20},
        {"name": "验证", "kind": "verifier", "duty": "只判", "criteria": "有结论", "budget": 5},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = Ledger(root / "ledger.jsonl")
        judge = Judge(authority=("leader",))
        for name, required in (("起草齐全", ["## 一、a", "## 二、b"]),
                               ("成稿齐全", ["## 一、a", "## 二、b", "## 三、c"])):
            judge.register(fc.tested(fc.propose_sections(name, required,
                                                        ("correctness", "test_quality"))),
                           proposer="leader")
        plan = fo.parse_plan("写一篇三段稿", ORG)

        pool = WorkerPool(root / "pool", ledger, workers=2, ttl=2.0).start()
        try:
            def prompt_builder(role, stage, upstream, attempt, feedback="", requirements=""):
                return (f"角色：{role.name}\n阶段：{stage}\n"
                        f"要求：{requirements}\n上游：{upstream[-200:]}")

            produce = PoolProducer(pool, prompt_builder, max_tokens=128, timeout=60,
                                   job_func="section_llm", usage=[])
            print(f"① 主进程 pid={os.getpid()}")
            print("② 跑一轮 PDCA：produce 经 worker 进程执行（假模型不出网）")
            pdca = PDCA(judge, ledger, plan, produce, fd.VOCAB)
            report = pdca.run(Declaration(goal="写一篇三段稿",
                                          dims=("correctness", "test_quality"),
                                          criteria=("起草齐全", "成稿齐全"),
                                          budget_tokens=100_000))
        finally:
            pool.stop()

        leased = [e for e in ledger.read() if e["kind"] == "dispatch_leased"]
        worker_pids = {e["payload"].get("pid") for e in leased}
        print("③ 账本里的派活")
        for event in ledger.read():
            if event["kind"] in ("dispatch", "dispatch_leased", "dispatch_done"):
                print(f"   {event['kind']:<16} {event['actor']:<4} "
                      f"pid={event['payload'].get('pid', '-')}")
        ok = (report["passed"] and leased
              and os.getpid() not in worker_pids)
        print(f"④ 结果：passed={report['passed']}  worker_pids={sorted(p for p in worker_pids if p)}"
              f"  主进程 pid={os.getpid()}  不相交={ok}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())