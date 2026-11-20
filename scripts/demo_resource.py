#!/usr/bin/env python3
"""S8 演示：资源账本 + 分档授权。

跑法：python3 scripts/demo_resource.py
池子 1000，自花阈值 100：小额直接花，大额进领导队列且不扣款，池不可超支。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sa2.core.ledger import Ledger  # noqa: E402
from sa2.core.resources import ResourceBook  # noqa: E402


def line(book: ResourceBook, label: str) -> None:
    print(f"   已花={book.spent()}  余额={book.remaining()}  待批={len(book.pending())}  [{label}]")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        book = ResourceBook(Ledger(path), total=1000, auto_ceiling=100)
        print(f"① 建账：池 {book.total()}，自花阈值 {book.auto_ceiling}")

        print("② 小额 80（≤ 阈值）→ 直接花")
        r = book.request(80, "跑一次小实验")
        print(f"   status={r['status']} approved_by={r.get('approved_by')}")
        line(book, "80")

        print("③ 大额 500（> 阈值）→ 进领导队列，一分不扣")
        big = book.request(500, "买一份数据")
        print(f"   status={big['status']} why={big['reason']}")
        line(book, "500 待批")

        print("④ 领导批准 → 这时才扣款")
        approved = book.approve(big["id"], by="leader")
        print(f"   status={approved['status']} approved_by={approved['approved_by']}")
        line(book, "500 已批")

        print("⑤ 要 2000（池不够）→ refused")
        over = book.request(2000, "买整库")
        print(f"   status={over['status']} why={over['reason']}")
        line(book, "2000 拒")

        print("⑥ 重放：换一个实例读同一本账，余额与待批队列都还在")
        replay = ResourceBook(Ledger(path), total=999)
        line(replay, "重放")
        print(f"   total={replay.total()}（以账本为准，不被人参参数 999 覆盖）")

        kinds = [e["kind"] for e in replay.ledger.read()]
        ok = (r["status"] == "approved" and big["status"] == "pending"
              and approved["status"] == "approved" and over["status"] == "refused"
              and replay.spent() == 580 and replay.pending() == []
              and kinds.count("resource_pool") == 1)
        print(f"⑦ 账本事件：{kinds}")
        print(f"   判定：{'过' if ok else '红'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())