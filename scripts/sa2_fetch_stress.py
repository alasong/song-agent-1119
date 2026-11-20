"""连续取数压测：验证限速与稳定性可复跑（不是压测工具，间隔默认 2s、最多 8 次）。

用法：python3 scripts/sa2_fetch_stress.py [--queries 4] [--gap 2]
退出码：0 = 全部命中；1 = 有失败（失败即停并打印原因）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.fetch import FetchError, search   # noqa: E402

QUERIES = [
    ('arxiv', 'all:"recursive self-improvement"'),
    ('hn', 'recursive self-improvement'),
    ('arxiv', 'all:"self-improving agent"'),
    ('hn', 'AI RSI'),
    ('arxiv', 'all:"agent evaluation"'),
    ('arxiv', 'all:"recursive improvement"'),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=4)
    ap.add_argument("--gap", type=float, default=2.0)
    args = ap.parse_args()

    rows, fails = [], 0
    for i, (source, query) in enumerate(QUERIES[: max(1, args.queries)], 1):
        started = time.time()
        try:
            items = search(source, query, 3)
            newest = max(x["published"] for x in items)
            rows.append({"n": i, "source": source, "ok": True, "entries": len(items),
                         "newest": newest, "secs": round(time.time() - started, 2)})
            print(f"[{i}] ok {rows[-1]['secs']}s {source} entries={len(items)} newest={newest}",
                  flush=True)
        except FetchError as exc:
            fails += 1
            rows.append({"n": i, "source": source, "ok": False, "error": str(exc)})
            print(f"[{i}] FAIL {source}: {exc}", flush=True)
        if i < args.queries:
            time.sleep(args.gap)
    print(json.dumps({"rows": rows, "fails": fails}, ensure_ascii=False, indent=2))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
