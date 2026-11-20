"""真网络自检：每个注册过的源真取一次，打印条数与耗时，任一失败就非零退出。

这是给「手到底还能不能用」的一个入口——不做假 transport、不 mock，直接打外网。
默认测试集不跑它（在 `tests_live/`），因为真网络慢且会抖。

    python3 scripts/live_check.py                 # 全部源
    python3 scripts/live_check.py --sources arxiv  # 只查一个
    python3 scripts/live_check.py --n 5 --json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2 import fetch                                   # noqa: E402

QUERIES = {
    "arxiv": 'all:"recursive self-improvement"',
    "hn": "recursive self improvement",
    "crossref": "recursive self improvement",
}


def check(source: str, n: int) -> dict:
    started = time.time()
    try:
        items = fetch.search(source, QUERIES.get(source, "recursive self improvement"), n)
        return {"source": source, "ok": True, "entries": len(items),
                "ms": int((time.time() - started) * 1000),
                "first": (items[0]["title"][:60] if items else "")}
    except Exception as exc:                      # 失败要大声：不打折扣地记下来
        return {"source": source, "ok": False, "entries": 0,
                "ms": int((time.time() - started) * 1000),
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="", help="逗号分隔；空=全部注册源")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wanted = [x.strip() for x in args.sources.split(",") if x.strip()] or fetch.source_names()
    rows = [check(source, args.n) for source in wanted]

    bad = [row for row in rows if not row["ok"]]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"真网络自检：{len(rows)} 个源")
        for row in rows:
            if row["ok"]:
                print(f"  {row['source']:<9} ok  {row['entries']} 条  {row['ms']:>5} ms  {row['first']}")
            else:
                print(f"  {row['source']:<9} 失败      {row['ms']:>5} ms  {row['error']}")
        print(f"结论：{len(rows) - len(bad)}/{len(rows)} 通")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
