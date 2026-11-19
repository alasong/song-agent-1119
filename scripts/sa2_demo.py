"""sa 2.0 端到端演示：跑一次完整的环，且**故意制造一次阶段拒绝**。

演示要证明的三件事（都是读数，不是说法）：
1. 判定权在外部：判据由 `forge.criteria` 提议、三反例自测通过后，由「领导」登记；
   生成方自己调 `judge.register(proposer="generator")` 会被拒。
2. 阶段绑角色：编制层面的派活次数 = 各阶段角色数之和（4 次），不是角色 × 阶段（6 次）。
3. 拒绝只重做该阶段：「成稿」第一次缺一节被阶段门拒，重做的只有「成稿」，
   起草阶段没有被重跑。

用法：python3 scripts/sa2_demo.py [--json]
退出码：0 = 全环跑通、passed=True、且确实发生过一次「只重做该阶段」
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.gate import Declaration            # noqa: E402
from sa2.core.judge import Judge, Unauthorized   # noqa: E402
from sa2.core.ledger import Ledger               # noqa: E402
from sa2.forge import criteria as forge_criteria  # noqa: E402
from sa2.forge import dims as forge_dims          # noqa: E402
from sa2.forge import goal as forge_goal          # noqa: E402
from sa2.forge import org as forge_org            # noqa: E402
from sa2.forge.scribe import Scribe               # noqa: E402
from sa2.loop.pdca import PDCA                    # noqa: E402
from sa2.memory.cases import CaseBook             # noqa: E402

SPEC = """必须包含：## 一、前提
必须包含：## 二、路径
必须包含：## 三、止损
"""

GOAL = "写一份 Agent 递归自我改进（RSI）的落地方案"

GOAL_JSON = json.dumps({"subtasks": [
    {"name": "写方案骨架", "deliverable": "三段式方案文档", "dims": ["correctness"]},
]}, ensure_ascii=False)

ORG_JSON = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆目标与验收", "criteria": "子任务可分别验收", "budget": 8000},
        {"name": "执行", "kind": "executor", "duty": "写正文", "criteria": "三节齐全", "budget": 30000},
        {"name": "验证", "kind": "verifier", "duty": "只判不写", "criteria": "逐条给结论", "budget": 5000},
    ],
    "stages": [
        {"name": "起草", "output": "前两节草稿", "roles": ["规划", "执行"], "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "完整三节", "roles": ["执行", "验证"], "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)

SECTION_1 = "## 一、前提\n改进回路必须先有可回滚的基线。\n"
SECTION_2 = "## 二、路径\n路径一：只改提示；路径二：改检索；路径三：改评据。\n"
SECTION_3 = "## 三、止损\n连续两轮无进展即停，并把失败案例入库。\n"


def fake_model(messages, max_tokens=1200):
    """确定性假模型：按提示词内容决定产出，用来代替真实调用。

    注意它接的是**真的** `forge.scribe.Scribe`（提示词拼装、失败原因传递、verifier 不产正文
    都走真实代码），只有「模型本身」是假的。
    """
    prompt = messages[0]["content"]
    if "职责：拆目标与验收" in prompt:
        return ""                                  # 规划出计划不产正文
    if "## 当前阶段\n成稿" in prompt:
        if "第 2 次尝试" not in prompt:
            return SECTION_1 + SECTION_2           # 成稿第一次：缺第三节，应被阶段门拒
        return SECTION_1 + SECTION_2 + SECTION_3
    return SECTION_1 + SECTION_2


def runs_root() -> Path:
    return Path(os.environ.get("XM_RUNS", str(Path.home() / "xm-runs"))).expanduser()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="机器读")
    args = ap.parse_args()

    run_dir = runs_root() / "sa2" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    cases = CaseBook(run_dir / "cases.jsonl")
    judge = Judge(authority=("leader", "verifier"), path=run_dir / "criteria.json")

    # ① 造判据：生成方提议 → 三反例自测 → 领导登记（判定权在外部）
    proposals = [
        forge_criteria.instantiate("必须包含：## 一、前提\n必须包含：## 二、路径",
                                   "起草齐全", ("correctness",)),
        forge_criteria.instantiate(SPEC, "成稿齐全", ("correctness", "test_quality")),
    ]
    tested = [forge_criteria.tested(c) for c in proposals]
    for crit in tested:
        judge.register(crit, proposer="leader")

    # 先证明这道门是活的：生成方抢登记权必须在门口被拦住
    blocked = False
    try:
        judge.register(tested[0], proposer="generator")
    except Unauthorized:
        blocked = True

    # ② 拆目标 + 声明维度 + 出编制（确定性输入，演示可复跑）
    subtasks = forge_goal.parse(GOAL, GOAL_JSON, forge_dims.VOCAB)
    declared_dims = forge_dims.declare(
        sorted({d for s in subtasks for d in s.dims} | {"test_quality"}))
    plan = forge_org.parse_plan(GOAL, ORG_JSON)

    decl = Declaration(goal=GOAL, dims=declared_dims,
                       criteria=("起草齐全", "成稿齐全"), budget_tokens=60_000)
    judge_run1 = Judge(authority=("leader",), require_self_tested=True)
    for crit in tested:
        judge_run1.register(crit, proposer="leader")
    scribe = Scribe(fake_model)
    pdca = PDCA(judge_run1, ledger, plan, scribe, forge_dims.VOCAB)

    # 第一跑：声明与阶段门都对，但证据给的是「见附件」——证据门必须红
    report1 = pdca.run(decl, evidence=["见附件"])

    # 第二跑：同一编制，证据换成真实文件与读数
    final = run_dir / "final.md"
    final.write_text(SECTION_1 + SECTION_2 + SECTION_3, encoding="utf-8")
    judge_run2 = Judge(authority=("leader",), require_self_tested=True)
    for crit in tested:
        judge_run2.register(crit, proposer="leader")
    pdca2 = PDCA(judge_run2, ledger, plan, Scribe(fake_model), forge_dims.VOCAB)
    report2 = pdca2.run(decl, evidence=[f"{final}:1", f"dispatches={report1['dispatches']}"])

    for reject in report1["rejects"]:
        cases.add(reject["stage"], "；".join(reject["problems"]), "补齐缺失章节后重做该阶段")

    readings = {
        "criteria": [c.name for c in tested],
        "self_test": "3/3 通过（合格件过、缺件拒、冒充件拒）",
        "generator_register_blocked": blocked,
        "plan": {"roles": [r.name for r in plan.roles],
                 "stages": [s.name for s in plan.stages],
                 "dispatches": plan.dispatches(),
                 "cartesian": len(plan.roles) * len(plan.stages)},
        "run_without_evidence": {"passed": report1["passed"], "rejects": len(report1["rejects"]),
                                 "redone": report1["redone"], "dispatches": report1["dispatches"],
                                 "problems": report1["problems"]},
        "run_with_evidence": {"passed": report2["passed"], "reason": report2["reason"],
                              "problems": report2["problems"],
                              "dispatches": report2["dispatches"]},
        "budget": report2["budget"],
        "ledger": str(ledger.path),
        "cases": len(cases.all()),
        "run_dir": str(run_dir),
    }

    # 一份编制跑两次：每次 起草 2 次派活 + 成稿 2 次派活 × 2 次尝试 = 6
    ok = (blocked
          and plan.dispatches() < len(plan.roles) * len(plan.stages)
          and len(report1["rejects"]) == 1
          and report1["redone"] == ["成稿"]
          and report1["dispatches"] == 6
          and not report1["passed"]          # 证据门该红
          and any("证据" in p for p in report1["problems"])
          and report2["passed"])

    if args.json:
        print(json.dumps({**readings, "ok": ok}, ensure_ascii=False, indent=2))
    else:
        p, r1 = readings["plan"], readings["run_without_evidence"]
        print("sa 2.0 全环演示（真 Scribe + 假模型）")
        print(f"  编制：{len(p['roles'])} 角色 / {len(p['stages'])} 阶段；编制层派活 "
              f"{p['dispatches']} 次（全连接会是 {p['cartesian']} 次）")
        print(f"  判据：{len(readings['criteria'])} 条，自测 {readings['self_test']}")
        print(f"  生成方抢登记权：{'被拦' if blocked else '未拦（红）'}")
        print(f"  第一跑（证据给「见附件」）：拒绝 {r1['rejects']} 次、重做 {r1['redone']}、"
              f"派活 {r1['dispatches']} 次 → passed={r1['passed']}")
        for problem in r1["problems"]:
            print(f"      红：{problem}")
        print(f"  第二跑（证据换真实文件与读数）：passed={readings['run_with_evidence']['passed']}")
        b = readings["budget"] or {}
        print(f"  预算：{b.get('spent')}/{b.get('tokens')} tokens"
              f"（{'真实 usage' if b.get('exact') else '字符估算'}），调用 {b.get('calls')} 次")
        print(f"  账本：{readings['ledger']}；案例 {readings['cases']} 条")
        print(f"结论：{'通过' if ok else '未通过'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())