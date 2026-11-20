#!/usr/bin/env python3
"""S2 演示：一个角色在某个阶段抛错，supervisor 发现、换人、任务照常跑完。

跑法：python3 scripts/demo_takeover.py
不碰仓库数据：写临时目录，跑完删掉。
"""
from __future__ import annotations

import json
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
from sa2.loop.supervisor import DispatchQueue, Supervisor  # noqa: E402
from sa2.memory.profiles import RoleProfile, RoleStore  # noqa: E402

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
        store = RoleStore(root / "roles.jsonl")
        queue = DispatchQueue(root / "dispatches.jsonl")

        judge = Judge(authority=("leader",))
        for name, required in (("起草齐全", ["## 一、a", "## 二、b"]),
                               ("成稿齐全", ["## 一、a", "## 二、b", "## 三、c"])):
            judge.register(fc.tested(fc.propose_sections(name, required,
                                                        ("correctness", "test_quality"))),
                           proposer="leader")
        plan = fo.parse_plan("写一篇三段稿", ORG)

        profile = RoleProfile(id="执行", kind="executor", duty="写")
        profile.add_promise("把第三节的引用补齐")
        store.save(profile)

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            if role.kind != "executor":
                return ""
            if stage == "起草":
                if "接管包" not in (feedback or ""):
                    print(f"  ✗ {role.name} 在「{stage}」抛错：模型通道断了")
                    raise RuntimeError("模型通道断了")
                print(f"  ✓ {role.name}（第 {store.get(role.name).generation} 代）"
                      f"收到接管包，接着写")
                return "## 一、a\n## 二、b\n"
            return "## 一、a\n## 二、b\n## 三、c\n"

        print("① 开跑（两阶段：起草 → 成稿）")
        supervisor = Supervisor(produce, ledger, store, queue, roles=plan.roles)
        pdca = PDCA(judge, ledger, plan, produce, fd.VOCAB, supervisor=supervisor)
        decl = Declaration(goal="写一篇三段稿", dims=("correctness", "test_quality"),
                           criteria=("起草齐全", "成稿齐全"), budget_tokens=100_000)
        report = pdca.run(decl)

        print("② 账本事件")
        for event in ledger.read():
            print(f"   {event['kind']:<12} {event['actor']}")
        takeover = [e for e in ledger.read() if e["kind"] == "takeover"][0]
        package = takeover["payload"]["package"]

        print("③ 接管包（继任者拿到的不是一句「你继续」）")
        print(f"   未偿承诺：{[x['text'] for x in package['promises']]}")
        print(f"   已完成部分：{package['partial'] or '（无）'}")
        print(f"   失败原因：{package['last_error']}")
        print(f"   上游尾部：{package['upstream_tail'][:40]!r}…")

        print("④ 派活队列")
        for dispatch in queue.all():
            print(f"   {dispatch.role_id}  {dispatch.stage}  {dispatch.state}")

        alive = store.get("执行")
        print(f"⑤ 档案：第 {alive.generation} 代，战绩 {alive.record}，"
              f"未偿承诺 {[x['text'] for x in alive.pending_promises()]}")
        print(f"⑥ 任务结果：passed={report['passed']}  dispatches={report['dispatches']}  "
              f"chars={report['chars']}")
        return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())