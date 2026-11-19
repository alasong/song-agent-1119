"""用真实模型跑一次 sa2 全环。

与 `sa2_demo.py` 的区别只有一条：这里的模型是真的。
所以读数里 `exact=True` 才是这次真花的 token，而且**判红也是有效读数**——
门在真模型上起作用，比门在假模型上起作用值钱。

编制走 L2 的规模决策：单一维度 + 两条判据 → 单人（一角色一阶段）。
第一次没过就带着失败原因重做一次，最多两次。

用法：
  python3 scripts/sa2_live.py            # 人读
  python3 scripts/sa2_live.py --json     # 机器读

退出码：
  0 = 环跑完且记账是真实 usage（passed 与否都算跑完）
  1 = 通道或流程出错
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

from sa2.core import gate                         # noqa: E402
from sa2.core.gate import Declaration             # noqa: E402
from sa2.core.judge import Judge                  # noqa: E402
from sa2.core.ledger import Ledger                # noqa: E402
from sa2.forge import criteria as fc              # noqa: E402
from sa2.forge import dims as fd                  # noqa: E402
from sa2.forge.scribe import Scribe               # noqa: E402
from sa2.loop import size                         # noqa: E402
from sa2.loop.pdca import PDCA                    # noqa: E402
from sa2.memory.cases import CaseBook             # noqa: E402
from xm.llm import complete_usage                 # noqa: E402

GOAL = "写一份「Agent 递归自我改进的最小可行实验」方案"

SPEC = """必须包含：## 一、基线
必须包含：## 二、改动
必须包含：## 三、止损
必须出现：验收方式：
"""

S1, S2, S3 = "## 一、基线", "## 二、改动", "## 三、止损"


def runs_root() -> Path:
    return Path(os.environ.get("XM_RUNS", str(Path.home() / "xm-runs"))).expanduser()


def make_llm(usage: list[dict]):
    def llm(messages, max_tokens: int = 1200):
        text, u = complete_usage(messages, model="deepseek-flash", max_tokens=max_tokens,
                                 extra={"thinking": {"type": "disabled"}})
        usage.append(u or {})
        return text
    return llm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    run_dir = runs_root() / "sa2-live" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(run_dir / "ledger.jsonl")
    cases = CaseBook(run_dir / "cases.jsonl")
    judge = Judge(authority=("leader",), path=run_dir / "criteria.json")

    # 判据由生成方提议、过三反例，再交给「领导」登记（判定权不在 sa2 手里）
    proposals = [
        fc.tested(fc.propose_sections("三节齐全", [S1, S2, S3], ("correctness",))),
        fc.tested(fc.propose_content("写清验收", ["验收方式："], ("correctness",))),
    ]
    for crit in proposals:
        judge.register(crit, proposer="leader")

    decl = Declaration(goal=GOAL, dims=("correctness",),
                       criteria=("三节齐全", "写清验收"), budget_tokens=60_000)
    plan, decision = size.plan_for(decl)

    usage: list[dict] = []
    scribe = Scribe(make_llm(usage), spec=SPEC, max_tokens=1500)
    pdca = PDCA(judge, ledger, plan, scribe, fd.VOCAB, usage=usage,
                max_stage_attempts=2, cases=cases)
    report = pdca.run(decl, evidence=[])

    # 产物落盘，再用它本身当证据过一遍证据门
    artifact = run_dir / "deliverable.md"
    artifact.write_text(report.get("text") or "", encoding="utf-8")
    evidence = [f"{artifact}:1", f"dispatches={report['dispatches']}"]
    evidence_problems = gate.check_evidence(evidence)
    delivery_ok = report["passed"] and not evidence_problems

    readings = {
        "scale": decision.scale,
        "scale_reason": decision.reason,
        "passed": delivery_ok,
        "delivery_passed": report["passed"],
        "evidence_problems": evidence_problems,
        "reason": report["reason"],
        "problems": report["problems"],
        "dispatches": report["dispatches"],
        "rejects": len(report["rejects"]),
        "redone": report["redone"],
        "chars": report["chars"],
        "budget": report["budget"],
        "exact_usage": bool((report["budget"] or {}).get("exact")),
        "criteria": judge.names(),
        "ledger": str(ledger.path),
        "run_dir": str(run_dir),
    }
    ok = bool(readings["exact_usage"]) and report["dispatches"] >= 1

    if args.json:
        print(json.dumps({**readings, "ok": ok}, ensure_ascii=False, indent=2))
    else:
        print("sa 2.0 真模型跑一轮")
        print(f"  规模决策：{decision.scale}（{decision.reason}）")
        print(f"  判据：{'、'.join(judge.names())}（均过三反例）")
        print(f"  派活 {report['dispatches']} 次，拒绝 {len(report['rejects'])} 次，"
              f"重做 {report['redone'] or '无'}")
        b = report["budget"] or {}
        print(f"  预算：{b.get('spent')}/{b.get('tokens')} tokens "
              f"（{'真实 usage' if b.get('exact') else '字符估算'}），调用 {b.get('calls')} 次")
        print(f"  证据门：{'过' if not evidence_problems else evidence_problems}")
        print(f"  结果：passed={delivery_ok}"
              + (f"，{report['reason']}" if report["reason"] else ""))
        for problem in report["problems"]:
            print(f"      红：{problem}")
        print(f"  账本：{readings['ledger']}")
        print(f"结论：{'跑通' if ok else '未跑通（无真实 usage 或没有派活）'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())