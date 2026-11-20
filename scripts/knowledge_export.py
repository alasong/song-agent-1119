"""把运行期攒下的经验导出成仓库里的一份种子。

为什么要有它：经验每天在 `~/xm-runs` 长，不能直接进 git——那样 diff 会被噪声淹没，
也没法 review。这一步是唯一的回流通道：**人跑它，人看 diff，人提交**。

筛选条件（可机检）：`injected ≥ --min-injected` 且 `ok/injected ≥ --min-rate`。
输出：`sa2/knowledge/seed/lessons.jsonl`（按 id 去重合并，不覆盖已有条目）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.memory import lessons as lessonbook        # noqa: E402
from sa2.memory import registry                    # noqa: E402

SEED = Path(__file__).resolve().parents[1] / "sa2" / "knowledge" / "seed" / "lessons.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-injected", type=int, default=3)
    ap.add_argument("--min-rate", type=float, default=0.8)
    ap.add_argument("--out", default=str(SEED))
    args = ap.parse_args()

    rows = lessonbook.all(registry.lessons_path())
    keep = [row for row in rows
            if int((row.get("stats") or {}).get("injected") or 0) >= args.min_injected
            and lessonbook._rate(row) >= args.min_rate]
    out = Path(args.out)
    if not keep:
        print(f"经验 {len(rows)} 条，够格 0 条：没有可导出的，不动 {out}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen.add(json.loads(line).get("id"))
                except json.JSONDecodeError:
                    continue
    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for row in keep:
            if row.get("id") in seen:
                continue
            fh.write(json.dumps({"id": row.get("id"), "when": row.get("when"),
                                 "text": row.get("text"), "fix": row.get("fix"),
                                 "origin": row.get("origin")}, ensure_ascii=False) + "\n")
            seen.add(row.get("id"))
            added += 1
    print(f"经验 {len(rows)} 条，够格 {len(keep)} 条，新导出 {added} 条 → {out}")
    print("这是给人 review 的：看完 diff 再提交，别让它自动进版本库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
