"""M0b-4：无人值守跑一次。启动后没有任何人工介入，直到它自己绿或失败。

用法：
    python3 scripts/m0b4_run.py [--rounds 8]
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

SPEC = """实现 xm/retry.py：

- `RetrierError`：异常类。
- `Retrier(max_attempts: int, base: float, factor: float = 2.0, sleep=time.sleep)`：
  - max_attempts < 1 → `RetrierError`；base <= 0 → `RetrierError`；factor <= 1 → `RetrierError`。
- `.delays()` → 长度等于 max_attempts 的退避列表，第 i 项 = base * factor**i。
- `.run(fn)` → 最多调用 fn 共 max_attempts 次：
  - 第一次成功即返回该值；
  - 失败后调用 `sleep(对应退避时长)` 再重试；
  - 全部失败时抛出最后一次的异常；
  - `.attempts` 记录实际调用次数（调用前可以不存在，调用后必须是整数）。
- 只用标准库。
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--out", default="reports/m0b4.json")
    ap.add_argument("--ledger", default="reports/m0b4_ledger.jsonl")
    args = ap.parse_args()

    out = Path("reports")
    out.mkdir(exist_ok=True)
    ledger = Ledger(args.ledger)
    cfg = DaemonConfig(
        spec=SPEC,
        target_file="xm/retry.py",
        tests=["tests.test_retry"],
        max_rounds=args.rounds,
        patience=3,
    )
    llm = lambda messages: complete(messages, model=args.model)
    daemon = Daemon(ledger, llm, cfg)
    summary = daemon.run()
    summary["experiment"] = "M0b-4"
    summary["model"] = args.model
    summary["driver"] = "none（启动后无人工介入）"
    Path(args.out).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["green_at_round"] else 1


if __name__ == "__main__":
    raise SystemExit(main())