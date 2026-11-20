#!/usr/bin/env python3
"""S3 演练：杀一个角色、杀一次进程，任务都要跑完。

  python3 scripts/drill_kill.py          # 假模型：角色死亡 + 进程硬杀两段
  python3 scripts/drill_kill.py --live   # 真模型：角色死亡一段（需要 DEEPSEEK_API_KEY）

退出码：0 = 两段都过；1 = 有一段没过；2 = --live 缺 key，不可跑。
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
from sa2.loop.supervisor import DispatchQueue, Supervisor  # noqa: E402
from sa2.loop.workers import WorkerPool  # noqa: E402
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


def _judge() -> Judge:
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", ["## 一、a", "## 二、b"]),
                           ("成稿齐全", ["## 一、a", "## 二、b", "## 三、c"])):
        judge.register(fc.tested(fc.propose_sections(name, required,
                                                    ("correctness", "test_quality"))),
                       proposer="leader")
    return judge


def _decl() -> Declaration:
    return Declaration(goal="写一篇三段稿", dims=("correctness", "test_quality"),
                       criteria=("起草齐全", "成稿齐全"), budget_tokens=100_000)


def _good(role, stage, upstream, attempt, feedback="", requirements=""):
    if role.kind != "executor":
        return ""
    if stage == "起草":
        return "## 一、a\n## 二、b\n"
    return "## 一、a\n## 二、b\n## 三、c\n"


def phase_role_death() -> bool:
    print("① 角色死亡：执行在「起草」抛错")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = Ledger(root / "ledger.jsonl")
        store = RoleStore(root / "roles.jsonl")
        queue = DispatchQueue(root / "dispatches.jsonl")
        profile = RoleProfile(id="执行", kind="executor", duty="写")
        profile.add_promise("把第三节的引用补齐")
        store.save(profile)

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            if role.kind != "executor":
                return ""
            if stage == "起草" and "接管包" not in (feedback or ""):
                print("   ✗ 执行 抛错：通道断了")
                raise RuntimeError("通道断了")
            print(f"   ✓ 执行（第 {store.get('执行').generation} 代）接着写")
            return _good(role, stage, upstream, attempt, feedback, requirements)

        plan = fo.parse_plan("写一篇三段稿", ORG)
        supervisor = Supervisor(produce, ledger, store, queue, roles=plan.roles)
        report = PDCA(_judge(), ledger, plan, produce, fd.VOCAB,
                      supervisor=supervisor).run(_decl())
        ok = report["passed"] and ledger.count("role_died") == 1 and ledger.count("takeover") == 1
        print(f"   账本：role_died={ledger.count('role_died')} takeover={ledger.count('takeover')}")
        print(f"   结果：passed={report['passed']}  档案第 {store.get('执行').generation} 代")
        return ok


def phase_process_kill() -> bool:
    print("② 进程硬杀：阶段中途 SystemExit，重启续跑")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        state = root / "state.json"
        plan = fo.parse_plan("写一篇三段稿", ORG)
        calls: list[str] = []

        def dying(role, stage, upstream, attempt, feedback="", requirements=""):
            calls.append(role.name)
            if role.kind != "executor":
                return ""
            raise SystemExit("模拟 kill -9：Exception 拦不住它")

        pdca = PDCA(_judge(), Ledger(root / "l1.jsonl"), plan, dying, fd.VOCAB,
                    state_path=state)
        try:
            pdca.run(_decl())
            print("   ✗ 没被杀掉，演练不成立")
            return False
        except SystemExit:
            pass

        saved = json.loads(state.read_text(encoding="utf-8"))
        done = [p["role"] for p in saved["partial"]["parts"]]
        print(f"   被杀时本阶段已完成：{done}")
        calls.clear()

        def good(role, stage, upstream, attempt, feedback="", requirements=""):
            calls.append(role.name)
            return _good(role, stage, upstream, attempt, feedback, requirements)

        pdca2 = PDCA(_judge(), Ledger(root / "l2.jsonl"), plan, good, fd.VOCAB,
                     state_path=state, resume=True)
        report = pdca2.run(_decl())
        ok = report["passed"] and "规划" not in calls and "执行" in calls
        print(f"   重启后调用：{calls}")
        print(f"   结果：passed={report['passed']}  已完成角色没重跑={'规划' not in calls}")
        return ok


def phase_worker_kill() -> bool:
    print("③ 进程级：kill -9 正在干活的 worker，另一个租约到期接手")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = Ledger(root / "ledger.jsonl")
        pool = WorkerPool(root, ledger, workers=2, ttl=1.0).start()
        try:
            did = pool.put("sa2.loop.jobs", "slow", 3.0, "接管完成")
            lease = pool.wait_lease(did, timeout=10)
            killed = pool.kill_holder(did) if lease else None
            print(f"   持有租约：{lease and lease.get('worker')}  → 被杀：{killed}")
            result = pool.wait(did, timeout=25)
            ok = (result["ok"] and result["out"] == "接管完成"
                  and result["worker"] != killed and ledger.count("takeover") == 1)
            print(f"   结果：ok={result['ok']} out={result['out']!r} 接手={result['worker']}")
            print(f"   账本：lease_expired={ledger.count('lease_expired')} "
                  f"takeover={ledger.count('takeover')}")
            return ok
        finally:
            pool.stop()


def live_produce():
    from sa2 import llm

    def produce(role, stage, upstream, attempt, feedback="", requirements=""):
        prompt = (f"你在一个交付组织里扮演「{role.name}」（{role.duty}）。\n"
                  f"阶段：{stage}\n验收要求：\n{requirements}\n\n"
                  f"上游：\n{(upstream or '')[-1500:]}\n\n"
                  "只输出要求里的标题与正文，不要解释。")
        return llm.complete([{"role": "system", "content": "只输出交付文本。"},
                             {"role": "user", "content": prompt}], max_tokens=1200)
    return produce


def phase_live() -> int:
    from sa2 import llm as channel

    try:
        channel.resolve_key()          # 环境变量可能没有；resolve_key 还会从运行中的 DSH 进程环境取
    except Exception:
        print("--live 不可跑：resolve_key 找不到可用 key（不拿假模型冒充真模型）")
        return 2
    print("③ 真模型：角色死亡后由继任者用真模型写完")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = Ledger(root / "ledger.jsonl")
        store = RoleStore(root / "roles.jsonl")
        queue = DispatchQueue(root / "dispatches.jsonl")
        real = live_produce()

        def produce(role, stage, upstream, attempt, feedback="", requirements=""):
            if role.kind == "executor" and stage == "起草" and "接管包" not in (feedback or ""):
                raise RuntimeError("演练注入：第一次派活断掉")
            return real(role, stage, upstream, attempt, feedback, requirements)

        plan = fo.parse_plan("写一篇三段稿", ORG)
        supervisor = Supervisor(produce, ledger, store, queue, roles=plan.roles)
        report = PDCA(_judge(), ledger, plan, produce, fd.VOCAB,
                      supervisor=supervisor).run(_decl())
        ok = report["passed"] and ledger.count("takeover") == 1
        print(f"   role_died={ledger.count('role_died')} takeover={ledger.count('takeover')} "
              f"passed={report['passed']}")
        return 0 if ok else 1


def main() -> int:
    if "--live" in sys.argv:
        return phase_live()
    if "--kill-worker" in sys.argv:
        return 0 if phase_worker_kill() else 1
    a = phase_role_death()
    b = phase_process_kill()
    print(f"\n演练结果：角色死亡={'过' if a else '红'}  进程硬杀={'过' if b else '红'}")
    return 0 if a and b else 1


if __name__ == "__main__":
    raise SystemExit(main())