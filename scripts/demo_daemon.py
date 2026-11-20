#!/usr/bin/env python3
"""M3 演示：常驻调度——有 approved 工单就领、跑完、空了退出；重启不重跑。

跑法：python3 scripts/demo_daemon.py
假模型不出网：证明的是调度语义，不是模型质量。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.autonomy.backlog import Backlog, Goal  # noqa: E402
from sa2.autonomy.daemon import drain  # noqa: E402
from sa2.core.judge import Judge  # noqa: E402
from sa2.core.ledger import Ledger  # noqa: E402
from sa2.forge import criteria as fc  # noqa: E402

DIMS = ("correctness",)


def make_judge() -> Judge:
    judge = Judge(authority=("leader",))
    judge.register(fc.tested(fc.propose_sections("章节齐全", ["## 一、a", "## 二、b"], DIMS)),
                   proposer="leader")
    return judge


def produce(role, stage, upstream, attempt, feedback="", requirements=""):
    return "## 一、a\n## 二、b\n"


def goal(text: str, **kw) -> Goal:
    base = dict(text=text, dims=DIMS, criteria=("章节齐全",), budget_tokens=10_000)
    base.update(kw)
    return Goal(**base)


def show(label: str, out: dict) -> None:
    print(f"{label}：ran={out['ran']} passed={out['passed']}")
    for tick in out["ticks"]:
        if tick.ran:
            print(f"   - {tick.goal.text}  passed={tick.report['passed']}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        book = Backlog(root / "backlog.jsonl")
        ledger = Ledger(root / "ledger.jsonl")
        judge = make_judge()
        vocab = {"correctness": "正确性"}

        print("① 队列里两个 approved 目标")
        book.add(goal("写第一份"))
        book.add(goal("写第二份"))
        first = drain(book, ledger, judge, produce, vocab, max_ticks=5)
        show("   第一次启动", first)

        print("② 重启：已完成的不重跑")
        second = drain(book, ledger, judge, produce, vocab, max_ticks=5)
        show("   第二次启动", second)

        print("③ 未批准的 self 目标：红线不领")
        book.add(goal("我自己想的目标", source="self", approved=False))
        third = drain(book, ledger, judge, produce, vocab, max_ticks=5)
        show("   第三次启动", third)

        ok = (first["ran"] == 2 and first["passed"] == 2
              and second["ran"] == 0 and third["ran"] == 0
              and ledger.count("daemon_start") == 3)
        print(f"④ 账本：daemon_start={ledger.count('daemon_start')} "
              f"daemon_stop={ledger.count('daemon_stop')}")
        print(f"   判定：{'过' if ok else '红'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())