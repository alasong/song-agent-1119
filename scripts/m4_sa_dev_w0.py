#!/usr/bin/env python3
"""M4 实测：给 SA 一个真实的 W0 开发工单，看它能不能自己改到绿。

工单：把 W0 形式化探针的任务清单从 10 条扩到 20+ 条，并提供 pick_tasks(n)。
验收：tests/test_w0_tasks.py（人先写好）。
只允许改 scripts/w0_formalize_probe.py；没变绿就还原，不让仓库停在半坏状态。

跑法：python3 scripts/m4_sa_dev_w0.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2 import llm as channel  # noqa: E402
from sa2.core.ledger import Ledger  # noqa: E402
from sa2.loop.dev import DevLoop, DevTicket  # noqa: E402

TARGET = "scripts/w0_formalize_probe.py"
TEST = [sys.executable, "-m", "unittest", "tests.test_w0_tasks", "-q"]


def main() -> int:
    target = ROOT / TARGET
    backup = target.read_text(encoding="utf-8")
    tokens: list[int] = []

    def model(messages, max_tokens=4000):
        text, usage = channel.complete_usage(
            messages, model="deepseek-flash", max_tokens=max_tokens,
            extra={"thinking": {"type": "disabled"}})
        tokens.append(int(usage.get("total_tokens") or 0))
        return text

    ticket = DevTicket(
        id="m4-w0",
        goal=("把 W0 形式化探针的任务清单扩到 20 条以上（编号唯一、描述具体），"
              "并新增 pick_tasks(n) 返回前 n 条；tests/test_w0_tasks.py 必须变绿。"),
        target=TARGET, test_cmd=TEST, max_rounds=3)

    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(Path(tmp) / "ledger.jsonl")
        out = DevLoop(model, ledger, ROOT, max_tokens=4000, timeout=180).run(ticket)
        events = [e["kind"] for e in ledger.read()]

    if not out["passed"]:
        target.write_text(backup, encoding="utf-8")
        print("没变绿，已还原原文件。")

    reading = {
        "step": "M4-sa-develops-w0", "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "passed": out["passed"], "rounds": out["rounds"],
        "calls": len(tokens), "tokens": sum(tokens),
        "restored": not out["passed"], "events": events,
        "last_output_tail": (out.get("output") or "")[-800:],
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    path = reports / f"m4-sa-dev-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"passed={out['passed']} rounds={out['rounds']} "
          f"calls={len(tokens)} tokens={sum(tokens)}")
    print(f"读数：{path.name}")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())