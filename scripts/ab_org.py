#!/usr/bin/env python3
"""S6：对超可判——同题双臂（组织 vs 单人）、同预算、盲评、帕累托。

  python3 scripts/ab_org.py            # 默认假模型（不出网），只比可测维度
  python3 scripts/ab_org.py --json     # 机器读
  python3 scripts/ab_org.py --judge llm  # 真模型盲评质量维（需要 DEEPSEEK_API_KEY）

判红条件：四件套（候选集 / 预算 / 判据版本 / 差值）缺一，最高只能 L0；
任一一臂未过判据，判「不合格」，不许称更优。
"""
from __future__ import annotations

import argparse
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
from sa2.loop import size  # noqa: E402
from sa2.loop.blind import blind_score  # noqa: E402
from sa2.loop.compare import verdict  # noqa: E402
from sa2.loop.pdca import PDCA  # noqa: E402

CRITERIA = ("起草齐全", "成稿齐全")
TEAM = json.dumps({
    "roles": [
        {"name": "规划", "kind": "planner", "duty": "拆解任务", "criteria": "有子任务", "budget": 100},
        {"name": "执行", "kind": "executor", "duty": "写正文", "criteria": "章节齐全", "budget": 200},
        {"name": "验证", "kind": "verifier", "duty": "独立判", "criteria": "有结论", "budget": 50},
    ],
    "stages": [
        {"name": "起草", "output": "草稿", "roles": ["规划", "执行"],
         "gate_criteria": ["起草齐全"]},
        {"name": "成稿", "output": "成稿", "roles": ["执行", "验证"],
         "gate_criteria": ["成稿齐全"]},
    ],
}, ensure_ascii=False)


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    for name, required in (("起草齐全", ["## 一、a", "## 二、b"]),
                           ("成稿齐全", ["## 一、a", "## 二、b", "## 三、c"])):
        judge.register(fc.tested(fc.propose_sections(name, required,
                                                    ("correctness", "test_quality"))),
                       proposer="leader")
    return judge


def make_produce(usage: list[dict]):
    def produce(role, stage, upstream, attempt, feedback="", requirements=""):
        usage.append({"total_tokens": 40 + len(upstream or "") // 50})
        if role.kind != "executor":
            return ""
        if stage == "起草":
            return "## 一、a\n## 二、b\n"
        return "## 一、a\n## 二、b\n## 三、c\n"
    return produce


def run_arm(name: str, plan, decl, judge: Judge, root: Path) -> dict:
    usage: list[dict] = []
    ledger = Ledger(root / f"{name}.jsonl")
    pdca = PDCA(judge, ledger, plan, make_produce(usage), fd.VOCAB)
    report = pdca.run(decl)
    return {"passed": report["passed"], "tokens": sum(u["total_tokens"] for u in usage),
            "chars": report["chars"], "dispatches": report["dispatches"],
            "text": report["text"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--budget", type=int, default=100_000)
    parser.add_argument("--judge", choices=("none", "llm"), default="none")
    args = parser.parse_args()

    decl = Declaration(goal="写一篇三段稿", dims=("correctness", "test_quality"),
                       criteria=CRITERIA, budget_tokens=args.budget)
    judge = make_judge()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        single = run_arm("single", size.single_plan(decl), decl, judge, root)
        team = run_arm("team", fo.parse_plan("写一篇三段稿", TEAM), decl, judge, root)
        texts = {"single": single.pop("text"), "team": team.pop("text")}
        arms = {"single": single, "team": team}
        dims = {"tokens": -1, "chars": 1}

        if args.judge == "llm":
            if not os.environ.get("DEEPSEEK_API_KEY"):
                print("--judge llm 不可跑：没有 DEEPSEEK_API_KEY", file=sys.stderr)
                return 2
            from sa2 import llm as channel
            blind = blind_score(texts["single"], texts["team"],
                                lambda m, max_tokens=None: channel.complete(m, max_tokens=1200))
            for arm_name, scores in (("single", blind["first"]), ("team", blind["second"])):
                arms[arm_name]["quality"] = sum(scores.values()) / len(scores)
            dims["quality"] = 1

        result = verdict(arms, budget=args.budget, criteria_version="sec-2026-11-20", dims=dims)
        result["blind_judge"] = args.judge == "llm"
        result["note"] = result.get("note", "") or (
            "假模型：只比可测维度；质量维需 --judge llm")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"级别：{result['level']}  赢家：{result['winner'] or '-'}")
        print(f"读数：{json.dumps(result['readings'], ensure_ascii=False)}")
        print(f"差值（对 baseline={result['baseline']}）："
              f"{json.dumps(result['deltas'], ensure_ascii=False)}")
        if result["problems"]:
            print("问题：" + "；".join(result["problems"]))
        print("说明：" + result.get("note", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())