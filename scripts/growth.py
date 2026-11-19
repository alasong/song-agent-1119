"""能力增长读数：回答「这轮比上轮强在哪」。

规则简单到能判红：
- 同族（同一任务）至少 2 次、且每次都有质量分，才允许说「在增长」；
- 最近一次的质量分低于该族历史最好 → 退化，判红；
- 没有质量分 → 只能报成本与通过率，不许叫能力增长。

退出码 0 只在「没有退化，且至少一族能声称增长」时给出。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xm.history import growth, load


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--history", default="")
    args = ap.parse_args()

    path = Path(args.history).expanduser() if args.history else None
    records, bad = load(path)
    table = growth(records)

    claimable = [f for f, row in table.items() if row["can_claim_growth"] and not row["regressed"]]
    regressed = [f for f, row in table.items() if row["regressed"]]
    unscored = [f for f, row in table.items() if row["scored_runs"] == 0]
    single = [f for f, row in table.items() if row["runs"] < 2]

    verdict = "能声称增长" if claimable and not regressed else "还不能声称增长"
    payload = {"total": len(records), "bad_lines": bad, "families": table,
               "claimable": claimable, "regressed": regressed,
               "unscored": unscored, "single_run": single, "verdict": verdict}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"记录 {len(records)} 条（坏行 {bad}）")
        for family, row in sorted(table.items()):
            best = row["best"]["quality"] if row["best"] else "-"
            print(f"- {family}：{row['runs']} 轮，打分 {row['scored_runs']} 轮，"
                  f"最好 {best}，最近 {row['last']['quality']}，"
                  f"调用 {row['last']['calls']}，退化={row['regressed']}")
        if unscored:
            print(f"没有质量分（只能比成本）：{unscored}")
        if single:
            print(f"只有一次运行（谈不上增长）：{single}")
        if regressed:
            print(f"退化：{regressed}")
        print(verdict)
    return 0 if claimable and not regressed else 1


if __name__ == "__main__":
    raise SystemExit(main())