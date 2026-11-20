"""真网络测试：验证「手真的能取到、戳真的打上」。

为什么不放进 `tests/`：这一组要真的连外网，单源 0.5–3 秒、还受网络与限速影响。
混进每天的绿灯里，要么让全量变慢，要么每次网络抖一下就有假红——两种都会让人开始
无视红。

手动跑：
    python3 -m unittest discover -s tests_live -t . -v
或者看读数：
    python3 scripts/live_check.py
"""
from __future__ import annotations

import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sa2 import fetch
from sa2.core.evidence import EvidenceBook

QUERIES = {
    "arxiv": 'all:"recursive self-improvement"',
    "hn": "recursive self improvement",
    "crossref": "recursive self improvement",
}
DATE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


class LiveSourcesTest(unittest.TestCase):
    """每个源真取一次：有条目、字段齐全、日期像日期、耗时可接受。"""

    def test_each_source_returns_real_entries(self):
        for source, query in QUERIES.items():
            with self.subTest(source=source):
                started = time.time()
                items = fetch.search(source, query, 3)
                elapsed = time.time() - started
                self.assertGreaterEqual(len(items), 1, f"{source} 一条都没取回")
                for item in items[:3]:
                    self.assertTrue(item["title"].strip(), f"{source} 条目没有标题")
                    self.assertTrue(item["url"].startswith("https://"),
                                    f"{source} 条目链接不是 https：{item['url']}")
                    self.assertRegex(item["published"], DATE,
                                     f"{source} 的日期形状不对：{item['published']!r}")
                    self.assertLessEqual(int(item["published"][:4]), 2100)
                self.assertLess(elapsed, 30, f"{source} 单次取数超过 30 秒")

    def test_real_entries_stamp_into_evidence(self):
        """真内容走一遍打戳：落盘、digest 与台账一致。"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = EvidenceBook(root / "evidence.jsonl")
            items = fetch.search("arxiv", QUERIES["arxiv"], 2)
            evs = fetch.record(items, book, root / "content", "live-test")
            self.assertEqual(len(book.all()), len({ev.digest for ev in evs}))
            for ev in evs:
                self.assertTrue(Path(ev.content_path).is_file(), "证据没有落盘")
                self.assertTrue(ev.fetched_at[:4].isdigit(), "取回时间不是系统打戳")

    def test_same_query_twice_does_not_inflate_the_ledger(self):
        """同一查询取两次：台账不该长——按内容寻址是一条，不是两条。"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = EvidenceBook(root / "evidence.jsonl")
            first = fetch.search("arxiv", QUERIES["arxiv"], 2)
            fetch.record(first, book, root / "content", "live-test")
            before = len(book.all())
            second = fetch.search("arxiv", QUERIES["arxiv"], 2)
            fetch.record(second, book, root / "content", "live-test")
            self.assertEqual(len(book.all()), before,
                             "同样的内容又被记成新证据：会撑高引用条数门槛")


if __name__ == "__main__":
    unittest.main()