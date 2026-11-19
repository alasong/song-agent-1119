"""M0b-5：让 daemon 做一个非编码任务（商业分析），看机制是否只擅长写代码。

用法：python3 scripts/m0b5_run.py --model deepseek-flash --rounds 4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.daemon import Daemon, DaemonConfig
from xm.ledger import Ledger
from xm.llm import complete

SPEC = """写一份决策文档，交付给读者本人的条件：
- 有 AI 工程能力（能做 agent / RAG / 微调 / 部署）
- 多年软件工程经验
- 缺行业垂直经验
- 目标是 6 个月内看到现金，不是做研究

文档结构必须严格如下（机检）：

## 结论
三句话以内说清先做哪个切入点、为什么。

## 候选切入点
至少 5 个，每个用三级标题开头，形如 `### 切入点1｜名称`，正文必须含四行标签：
- `客户：` 谁付钱，具体到角色（不是「企业」）
- `定价：` 怎么收钱、单价或计费单位
- `证据：` 支撑这个判断的可验证事实（公开案例、招投标、招聘需求、价格页）
- `风险：` 这条路最可能死在哪

候选里必须覆盖：AI 漫剧/短剧、FDE（前向部署工程师）、垂直行业 AI 交付、内容工具、教育/电商等方向，并说明为什么适合或不适合「缺垂直经验 + 有工程能力」的人。

## 90 天行动
分 30 天 / 60 天 / 90 天三段，每段给出可交付物与验证方式。

## 反证条件
至少 2 条：出现什么信号就说明这条路不通，该停。

要求：中文，务实，不要商业黑话，不要罗列「AI 是趋势」这种正确的废话。全文不少于 1500 字。
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--out", default="reports/m0b5.json")
    ap.add_argument("--ledger", default="reports/m0b5_ledger.jsonl")
    args = ap.parse_args()

    ledger = Ledger(args.ledger)
    cfg = DaemonConfig(
        spec=SPEC,
        target_file="docs/ai-money.md",
        tests=["tests.test_analysis"],
        max_rounds=args.rounds,
        patience=2,
        fence_lang="markdown",
    )
    llm = lambda messages: complete(messages, model=args.model, max_tokens=8000)
    summary = Daemon(ledger, llm, cfg).run()
    summary.update({"experiment": "M0b-5", "model": args.model,
                    "task": "AI 行业变现分析（非编码任务）"})
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["green_at_round"] else 1


if __name__ == "__main__":
    raise SystemExit(main())