"""编号分配：从台账里已有 S 编号的最大值 +1 起算，跨批去重也不撞号。

真跑崩在 `证据 id 重复：S10`：旧实现按 `len(book) + 1` 起算，去重之后 len 不长，
新条目就会拿到一个已经用过的编号。这里钉住修复后的三条不变量，对应
`sa2/fetch.py::record` 里的 `next_index = max(int(start), _max_index(book) + 1)`。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.evidence import EvidenceBook, EvidenceError, stamp
from sa2.fetch import _max_index, record


def entry(title: str, published: str = "2026-11-01",
          url: str = "https://example.org/paper", summary: str = "摘要正文") -> dict:
    """`record` 只读这四个字段；重复条目必须四个字段完全一致，digest 才相同。"""
    return {"title": title, "published": published, "url": url, "summary": summary}


class ChainedRecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "content"
        self.book = EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")

    def test_three_batches_with_cross_batch_duplicates_never_collide(self):
        a, b = entry("A 标题"), entry("B 标题")
        c, d = entry("C 标题"), entry("D 标题")
        e = entry("E 标题")
        # 每批都按真实调用方式传 start=len(book.all())+1：去重后 len 不长，这是要害
        batches = [[a, b, a], [c, d], [b, e]]
        seen: list[list[str]] = []
        try:
            for batch in batches:
                got = record(batch, self.book, self.root, "leader",
                             start=len(self.book.all()) + 1)
                seen.append([ev.evidence_id for ev in got])
        except EvidenceError as exc:          # 旧实现就是在这里崩的
            self.fail(f"record 抛了 EvidenceError：{exc}")
        # 批内重复复用原 id；批间重复（B）也复用批 1 分配的 S2，不新增编号
        self.assertEqual(seen, [["S1", "S2", "S1"], ["S3", "S4"], ["S2", "S5"]])
        all_ids = [ev.evidence_id for ev in self.book.all()]
        self.assertEqual(len(all_ids), 5, "A/B/C/D/E 五条，重复不重复入账")
        self.assertEqual(sorted(all_ids), ["S1", "S2", "S3", "S4", "S5"])
        self.assertEqual(len(set(all_ids)), 5, "编号必须唯一，否则 [Sx] 会指到两份材料")

    def test_hand_seeded_s9_is_kept_and_next_id_is_s10(self):
        # 真实路径塞一条 S9：stamp 落盘 + add 入账，和 record 内部走的是同两条路
        seeded = stamp("https://example.org/paper9", "第九条正文", "leader", "S9",
                       self.root)
        self.book.add(seeded)
        got = record([entry("S9 之后的新材料")], self.book, self.root, "leader",
                     start=len(self.book.all()) + 1)
        self.assertEqual([ev.evidence_id for ev in got], ["S10"],
                         "从最大已有编号 +1 起算，既不回退到 S1，也不撞 S9")
        self.assertEqual(sorted(ev.evidence_id for ev in self.book.all()),
                         ["S10", "S9"])


class MaxIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "content"
        self.book = EvidenceBook(Path(self.tmp.name) / "evidence.jsonl")

    def _seed(self, evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            content = f"第 {evidence_id} 条内容"
            ev = stamp(f"https://example.org/{evidence_id}", content, "leader",
                       evidence_id, self.root)
            self.book.add(ev)

    def test_returns_biggest_s_index_and_ignores_other_shapes(self):
        self._seed(["S3", "S11", "E7"])
        self.assertEqual(_max_index(self.book), 11, "E7 不是 S<n> 形态，忽略")

    def test_empty_book_is_zero(self):
        self.assertFalse(self.book.path.exists(), "空台账连文件都不该有")
        self.assertEqual(_max_index(self.book), 0)


if __name__ == "__main__":
    unittest.main()