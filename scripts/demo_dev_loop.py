#!/usr/bin/env python3
"""M1 演示：代码工单回路——改到绿、失败带输出重做、越界拦截。

  python3 scripts/demo_dev_loop.py          # 假模型（两轮，确定性）
  python3 scripts/demo_dev_loop.py --live   # 真模型修同一个 bug
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2 import llm as channel  # noqa: E402
from sa2.core.ledger import Ledger  # noqa: E402
from sa2.loop.dev import DevLoop, DevRefused, DevTicket  # noqa: E402

BAD = "```python\ndef add(a, b):\n    return 0\n```"
GOOD = "```python\ndef add(a, b):\n    return a + b\n```"


def fixture(root: Path) -> None:
    (root / "src.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (root / "test_demo.py").write_text(
        "import unittest\nfrom src import add\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")


def ticket() -> DevTicket:
    return DevTicket(id="demo", goal="让 test_demo 的 test_add 变绿", target="src.py",
                     test_cmd=[sys.executable, "-m", "unittest", "test_demo", "-q"],
                     max_rounds=3)


def main() -> int:
    live = "--live" in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture(root)
        ledger = Ledger(root / "ledger.jsonl")

        if live:
            def model(messages, max_tokens=2000):
                return channel.complete(messages, max_tokens=max_tokens,
                                        extra={"thinking": {"type": "disabled"}})
            print("① 真模型：修 add() 的 bug")
            out = DevLoop(model, ledger, root).run(ticket())
        else:
            replies = iter([BAD, GOOD])

            def model(messages, max_tokens=2000):
                return next(replies)

            print("① 假模型：第一轮写错 → 第二轮带着失败输出改对")
            out = DevLoop(model, ledger, root).run(ticket())

        print(f"   passed={out['passed']} rounds={out['rounds']}")
        print(f"   文件现在：{(root / 'src.py').read_text(encoding='utf-8').strip()!r}")

        print("② 账本")
        for event in ledger.read():
            print(f"   {event['kind']:<12} {event['payload'].get('round', '-')} "
                  f"rc={event['payload'].get('rc', '-')}")
        return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())