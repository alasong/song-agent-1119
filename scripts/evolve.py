"""把够格的经验提升成「机制候选」——只产候选，不生效。

为什么要有这个入口：`sa2/memory/evolution.py` 只是一段逻辑，没人调用它，候选就永远不存在；
而 `scripts/candidate_promote.py` 已经等着读 candidates.jsonl 了。这条命令把两头接上。

    python3 scripts/evolve.py                 # 按默认门槛（同 when ≥2 条、成功率 ≥0.8）
    python3 scripts/evolve.py --min-support 3 --min-rate 0.9 --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.memory import evolution, registry           # noqa: E402
from sa2.memory import lessons as lessonbook        # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-support", type=int, default=2)
    ap.add_argument("--min-rate", type=float, default=0.8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = lessonbook.all(registry.lessons_path())
    found = evolution.candidates(rows, min_support=args.min_support, min_rate=args.min_rate)
    print(f"经验 {len(rows)} 条 → 够格候选 {len(found)} 条"
          f"（门槛：同 when ≥{args.min_support} 条、成功率 ≥{args.min_rate}）")
    for item in found:
        print(f"  when={item['when']} support={item['support']} "
              f"rate={item['rate']} ids={item['ids']}")
    if args.dry_run:
        print("dry-run：没有写 candidates.jsonl")
        return 0
    added = evolution.write(registry.candidates_path(), found)
    print(f"新写入候选 {added} 条 → {registry.candidates_path()}")
    if found:
        print("下一步：python3 scripts/candidate_promote.py --list 看候选，"
              "--id N --apply 才生效（登记方必须是 leader/verifier）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
