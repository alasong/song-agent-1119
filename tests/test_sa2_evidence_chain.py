"""证据链两处新行为的测试：

A. `sa2/fetch.py::record` 按内容去重：同一份内容只入账一次，重复取回复用原 id；
B. `sa2/core/evidence.py::reference_ids` / `check_references`：正文里的 arXiv/DOI
   编号要归一后去重，且每一条都得能在证据台账（uri 或落盘内容）里找到。

全程不碰网络：`record` 只是把给它的 entry 落盘打戳；台账与内容根都放
TemporaryDirectory。证据用真实的 `EvidenceBook` + `stamp(...)` 造，不手写 jsonl。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa2.core.evidence import (                  # noqa: E402
    EvidenceBook, check_references, reference_ids, stamp,
)
from sa2.fetch import record                     # noqa: E402

# record 读这四个键：title / published / url / summary（content 由它们拼成）。
ENTRY = {
    "title": "Piccolo: Co-Evolving Decision Models",
    "published": "2026-11-18T00:00:00Z",
    "url": "https://arxiv.org/abs/2611.00001v1",
    "summary": "We study recursive self improvement.",
}


class EvidenceChainTest(unittest.TestCase):
    # ── A. record 的内容去重 ────────────────────────────────────────────────

    def test_record_same_content_returns_two_but_one_ledger_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = EvidenceBook(Path(tmp) / "evidence.jsonl")
            out = record([dict(ENTRY), dict(ENTRY)], book, Path(tmp) / "store", "leader")

            # 两条都返回（调用方拿得到两条材料），但指向同一条证据。
            self.assertEqual(len(out), 2)
            self.assertEqual(out[0].evidence_id, out[1].evidence_id)
            self.assertEqual(len(book.all()), 1)
            self.assertEqual(book.all()[0].evidence_id, out[0].evidence_id)

    def test_record_different_content_gets_two_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = EvidenceBook(Path(tmp) / "evidence.jsonl")
            other = dict(ENTRY, title="BaseRSI: A Different Paper")
            out = record([dict(ENTRY), other], book, Path(tmp) / "store", "leader")

            self.assertEqual(len(out), 2)
            self.assertEqual(len({ev.evidence_id for ev in out}), 2)
            self.assertEqual(len(book.all()), 2)
            self.assertEqual({ev.evidence_id for ev in book.all()},
                             {ev.evidence_id for ev in out})

    def test_record_same_entries_again_reuses_ids_without_growing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = EvidenceBook(Path(tmp) / "evidence.jsonl")
            root = Path(tmp) / "store"
            first = record([dict(ENTRY)], book, root, "leader")
            second = record([dict(ENTRY)], book, root, "leader")

            # 内容寻址：第二次直接复用原 id，台账不再长一条。
            self.assertEqual(second[0].evidence_id, first[0].evidence_id)
            self.assertEqual(len(book.all()), 1)

    # ── B. reference_ids 归一 ───────────────────────────────────────────────
    def test_reference_ids_normalizes_orders_and_dedups(self):
        text = (
            "参考文献：\n"
            "DOI: 10.1038/S41586-023-06792-0。\n"
            "https://arxiv.org/abs/2406.04383v2\n"
            "arXiv:2408.06292v2，以及重复的 arXiv:2408.06292v3\n"
            "另一个 doi.org 链接：https://doi.org/10.1038/s41586-023-06792-0。\n"
        )
        # 去版本号、全小写、按首次出现顺序、去重；中文句号不许粘在 DOI 尾巴上。
        self.assertEqual(
            reference_ids(text),
            ["10.1038/s41586-023-06792-0", "2406.04383", "2408.06292"],
        )

    def test_reference_ids_empty_when_no_identifiers(self):
        self.assertEqual(reference_ids("本文没有任何文献编号，只有普通叙述。"), [])

    # ── B. check_references 台账核对 ────────────────────────────────────────
    def _book_with_arxiv(self, tmp: Path) -> Path:
        """真实 stamp + EvidenceBook：台账里有一条 uri 含 2406.04383 的证据。"""
        book = EvidenceBook(tmp / "evidence.jsonl")
        ev = stamp("https://arxiv.org/abs/2406.04383v2",
                   "Piccolo 摘要正文", "leader", "S1", tmp / "store")
        book.add(ev)
        return book.path

    def test_check_references_accepts_id_present_in_ledger_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._book_with_arxiv(Path(tmp))
            # 台账 uri 含 2406.04383 ⇒ 正文提它不算凭记忆。
            self.assertEqual(
                check_references("采用 https://arxiv.org/abs/2406.04383 的方案。",
                                 {"book": str(path)}),
                [])

    def test_check_references_flags_id_absent_from_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._book_with_arxiv(Path(tmp))
            problems = check_references("另引 arXiv:2408.06292v2 的说法。",
                                        {"book": str(path)})
            self.assertEqual(len(problems), 1)
            self.assertIn("2408.06292", problems[0])

    def test_check_references_requires_book_in_spec(self):
        problems = check_references("arXiv:2408.06292v2", {})
        self.assertEqual(len(problems), 1)
        self.assertIn("缺 book", problems[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()